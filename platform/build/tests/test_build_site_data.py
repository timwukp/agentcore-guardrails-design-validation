"""Tests for the payload builder — the single writer of everything the platform serves.

WHAT THIS FILE IS FOR, AND WHAT IT DELIBERATELY LEAVES ALONE
------------------------------------------------------------
`check_site_invariants.py` already asserts properties of a FINISHED payload, and it runs in the publish
gate on every release. Repeating it here would be a second copy of the same policy with no second
source of truth to justify it. So this file tests the things only a test can reach:

* the builder's REFUSALS — the families gate, and the output-root guards. A refusal has no artifact, so
  nothing downstream can check it; if it silently stopped refusing, every gate after it would still
  pass and the missing classification would become "unrestricted by omission".
* the builder's own PROVENANCE claims — that `inputs_sha256` names files that exist and hashes them
  correctly, and that `provenance` is total over the payload. `gate_payload.py` grants redaction
  exceptions by inheriting them along `provenance`, so a wrong entry there is how a real leak would
  inherit a waiver it was never granted.
* the SERIES SPLIT, which is invisible from either side alone: the heavy arrays must be absent from
  the case page and present in the series file, and `series_available` must name exactly them.
* the pass-through of `--figure-check-rc`, whose three states (0 / non-zero / omitted) are the
  difference between "verified", "drifted" and "not verified" on the figure gallery. A default of 0
  would render an unrun check as verified, which is the one wrong answer of the three.

Counts are DERIVED here, never memorised (`feedback_test_suite_over_memory`): the number of registered
cases comes from the register, the published count from the verdict files. A test asserting `93` would
pass a build that dropped a case and gained a duplicate.

One build is shared across the tests that only read a payload, because a build takes ~20 s and none of
those tests mutate it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BUILD = REPO / "platform" / "build"
FAMILIES_YAML = REPO / "platform" / "curation" / "families.yaml"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, BUILD / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bsd = _load("build_site_data")


# --------------------------------------------------------------------------- one shared build

@pytest.fixture(scope="module")
def payload(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("payload-build") / "payload"
    rc = bsd.main(["--out", str(out), "--stamp", "20260101T000000Z", "--figure-check-rc", "0"])
    assert rc == 0
    return out


def read(payload: Path, rel: str):
    return json.loads((payload / rel).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- the families gate
#
# Six refusals plus the duplicate-key arm, each driven by a mutated copy of the YAML handed to the
# deriver through a patched reader. The real file is never written to: a test that edits an authored
# governance file is one interrupted run away from leaving it edited.

def families_text() -> str:
    return FAMILIES_YAML.read_text(encoding="utf-8")


def run_families(monkeypatch, text: str):
    """Call derive_families with `text` standing in for the authored file."""
    original = bsd.read_text

    def fake(path, inputs):
        if Path(path).name == "families.yaml":
            inputs["platform/curation/families.yaml"] = bsd.sha256_bytes(text.encode())
            bsd.note_read("platform/curation/families.yaml")
            return text
        return original(path, inputs)

    monkeypatch.setattr(bsd, "read_text", fake)
    inputs: dict[str, str] = {}
    cases = bsd.derive_register(inputs)[0]
    with bsd.scope():
        return bsd.derive_families(inputs, cases)


def test_no_mutant_control_the_authored_file_passes(monkeypatch):
    """First, so a red result below is attributable to the mutation and not to the harness."""
    out = run_families(monkeypatch, families_text())
    assert out["families"], "derive_families returned no families at all"
    # Every registered family classified, and the per-family case counts partition the register.
    inputs: dict[str, str] = {}
    cases = bsd.derive_register(inputs)[0]
    assert sum(v["n_cases"] for v in out["families"].values()) == len(cases)
    assert set(out["families"]) == {v[0] for v in cases.values()}


@pytest.mark.parametrize(
    ("name", "mutate", "expect"),
    [
        (
            "a registered family loses its classification",
            lambda t: _drop_family(t, "F6"),
            "does not classify",
        ),
        (
            "an entry for a family no case belongs to",
            lambda t: t + "\n  F99:\n    label: x\n    cost: billable\n    runner: any\n"
                          "    mutates: nothing\n    schedulable: true\n"
                          "    network_position_sensitive: false\n",
            "classifies",
        ),
        (
            "a required field is missing",
            lambda t: t.replace("    schedulable: false", "    schedulable_MISSPELLED: false", 1),
            "has no `schedulable`",
        ),
        (
            "a value outside the declared vocabulary",
            lambda t: t.replace("    cost: billable", "    cost: cheap-ish", 1),
            "outside the declared vocabulary",
        ),
        (
            "not schedulable and no reason given",
            lambda t: _drop_line(t, "why_not_schedulable"),
            "gives no reason",
        ),
        (
            "network-position sensitive with no banner text",
            lambda t: _blank_value(t, "replication_requirement"),
            "no `replication_requirement`",
        ),
    ],
)
def test_families_gate_refuses(monkeypatch, name, mutate, expect):
    text = mutate(families_text())
    assert text != families_text(), f"the mutation for {name!r} did not change the file"
    with pytest.raises(bsd.BuildError) as err:
        run_families(monkeypatch, text)
    assert expect in str(err.value), f"{name}: refused for the wrong reason: {err.value}"


def test_duplicate_key_is_refused_rather_than_silently_last_wins(monkeypatch):
    """PyYAML keeps the last of two identical keys. In an authored governance file that means an
    edit can be overridden by a line the author cannot see, so the loader refuses instead.

    The mutant inserts a SECOND `schedulable:` into F6 — the family whose whole point is that it is
    not schedulable — and the inserted one says `true`. Under plain `safe_load` the authored
    `schedulable: false` wins only because it happens to come second in the file; reverse the two
    lines and F6 becomes schedulable with no visible edit. That is the failure mode, and it is why
    the check is on the loader rather than on the value.
    """
    text = families_text().replace("  F6:", "  F6:\n    schedulable: true", 1)
    assert text != families_text(), "the duplicate-key mutation did not change the file"
    with pytest.raises(bsd.BuildError) as err:
        run_families(monkeypatch, text)
    assert "defines the key 'schedulable' twice" in str(err.value), (
        f"refused, but not as a duplicate key: {err.value}"
    )


def _drop_family(text: str, family: str) -> str:
    """Remove one family's whole entry: the key line and every line indented under it.

    Renaming the key instead would trip BOTH directions of the check at once (the register's family
    is missing AND an unregistered one is present), so the test could not tell which arm killed it.
    """
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln == f"  {family}:")
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or lines[end].startswith("    ")):
        end += 1
    out = lines[:start] + lines[end:]
    assert len(out) < len(lines) - 3, f"dropping {family} removed only {len(lines) - len(out)} lines"
    return "\n".join(out) + "\n"


def _drop_line(text: str, key: str) -> str:
    kept = [ln for ln in text.splitlines() if f"{key}:" not in ln]
    assert len(kept) < len(text.splitlines()), f"no line carrying {key}:"
    return "\n".join(kept) + "\n"


def _blank_value(text: str, key: str) -> str:
    out = []
    changed = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{key}:"):
            out.append(f"{line[: len(line) - len(line.lstrip())]}{key}: \"\"")
            changed = True
        elif changed and (line.startswith("      ") or not stripped):
            # Drop the continuation lines of the folded scalar we just replaced.
            continue
        else:
            if changed and stripped and not line.startswith("      "):
                changed = False
            out.append(line)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- the output-root guards

@pytest.mark.parametrize("rel", ["results/phase1/x", "claims/x", "lib/x", "site/data", "."])
def test_refuses_to_write_inside_the_repository(rel):
    """Not tidiness. A payload inside ROOT is also read by `check_redaction.py`, which would then have
    to waive a derived copy of every reviewed exception its sources already carry — measured
    2026-08-19: 44 findings, all second copies of two already-reviewed lines, which is how a real
    45th hides. And the alternative, adding the directory to SKIP_DIRS, is the one change that makes
    that gate blind to the exact bytes we publish."""
    with pytest.raises(bsd.BuildError) as err:
        bsd.main(["--out", str(REPO / rel), "--figure-check-rc", "0"])
    assert "refusing an output root" in str(err.value)


# --------------------------------------------------------------------------- provenance

def test_every_recorded_input_exists_and_hashes_to_the_recorded_value(payload: Path):
    """The manifest's whole purpose is to let a reader prove which tree the payload came from."""
    manifest = read(payload, "MANIFEST.json")
    inputs = manifest["inputs_sha256"]
    assert len(inputs) == manifest["n_inputs"] > 100
    for rel, want in inputs.items():
        source = REPO / rel
        assert source.is_file(), f"{rel} is recorded as an input but is not in the repository"
        got = hashlib.sha256(source.read_bytes()).hexdigest()
        assert got == want, f"{rel} hashes {got[:12]}…, manifest records {want[:12]}…"


def test_provenance_is_total_over_the_payload_and_names_real_sources(payload: Path):
    """`gate_payload.py` inherits a reviewed redaction exception ALONG this mapping. A file with no
    provenance would need a waiver of its own, and a wrong source would inherit somebody else's."""
    manifest = read(payload, "MANIFEST.json")
    provenance = manifest["provenance"]
    on_disk = {p.relative_to(payload).as_posix() for p in payload.rglob("*") if p.is_file()}
    assert set(provenance) == on_disk, (
        f"provenance and the payload differ on {sorted(set(provenance) ^ on_disk)[:5]}"
    )
    inputs = set(manifest["inputs_sha256"])
    for rel, sources in provenance.items():
        assert sources, f"{rel} claims no source"
        unknown = [s for s in sources if s not in inputs]
        assert not unknown, f"{rel} names sources this build never read: {unknown[:3]}"


def test_a_case_page_inherits_its_own_verdict_file_and_not_another_cases(payload: Path):
    """The granularity is the point: `cases/F5-7b.json` must inherit F5-7b's reviewed exception and
    nobody else's. If every page listed every source, one waived line would waive it everywhere.

    "Its own" includes a case's SUB-ARTIFACTS, and that is not a loophole. `F3-10` publishes
    `F3-10_log_surface_join.json` and `F3-10_window_audit.json` alongside its verdict file, and the
    builder lists them in `_no_verdict_files` precisely so the page can render them; they are
    F3-10's own bytes, reviewed with F3-10. What must never appear is another CASE's file, so the
    rule is a prefix on the case id at a separator — `F5-7b.json` is still foreign to `F5-7`,
    because `F5-7b` neither equals `F5-7` nor starts with `F5-7_`.
    """
    provenance = read(payload, "MANIFEST.json")["provenance"]
    checked, sub_artifacts = 0, 0
    for rel, sources in provenance.items():
        if not rel.startswith("cases/"):
            continue
        cid = rel[len("cases/"):-len(".json")]
        verdicts = [s for s in sources if s.startswith("results/phase1/") and "/archive/" not in s]
        own, others = [], []
        for s in verdicts:
            stem = Path(s).stem.split("__")[0]
            (own if stem == cid or stem.startswith(f"{cid}_") else others).append(s)
        assert not others, f"{rel} inherits another case's verdict file: {others[:3]}"
        sub_artifacts += sum(1 for s in own if Path(s).stem.split("__")[0] != cid)
        checked += 1
    assert checked > 50, f"only {checked} case pages examined; the loop found almost nothing"
    assert sub_artifacts > 0, (
        "no page inherited a sub-artifact, so the widened rule above was never exercised and this "
        "test would pass just as well with the strict equality it replaced"
    )


# --------------------------------------------------------------------------- the series split

def test_the_split_moves_the_heavy_arrays_and_names_exactly_them(payload: Path):
    """A case page must be small enough to render immediately and must not silently lose data. The
    two halves are only checkable together: `series_available` names keys whose ARRAY is in the
    series file and whose place in the page holds a stub instead.

    The stub, not absence, is what makes the split honest. Deleting the array would leave a page that
    cannot say what it is missing; the stub carries `n` and `bytes`, so the UI can tell a series of
    293 requests from one of 3 before fetching either, and a reader can see that something was moved
    rather than never measured.
    """
    split_cases, stubs = 0, 0
    for page_path in sorted((payload / "cases").glob("*.json")):
        page = json.loads(page_path.read_text(encoding="utf-8"))
        available = page["series_available"]
        if not available:
            continue
        split_cases += 1
        series = read(payload, f"series/{page['case']}.json")["series"]
        assert sorted(series) == sorted(available), (
            f"{page['case']}: series_available {available} but the series file holds {sorted(series)}"
        )
        for key in available:
            node: object = page["record"]
            for part in key.split("."):
                assert isinstance(node, dict) and part in node, (
                    f"{page['case']}: the split recorded {key} but the page has no such path, so the "
                    f"page cannot say what was moved"
                )
                node = node[part]
            assert isinstance(node, dict) and node.get("$series") == key, (
                f"{page['case']}: {key} holds {type(node).__name__} in the page — the heavy array "
                f"must be replaced by a stub naming its own path, not left in place"
            )
            assert node["n"] == len(series[key]), (
                f"{page['case']}: {key}'s stub claims n={node['n']} but the series file holds "
                f"{len(series[key])} elements"
            )
            assert node["bytes"] >= bsd.SERIES_BYTES, (
                f"{page['case']}: {key} was split at {node['bytes']} bytes, under the "
                f"{bsd.SERIES_BYTES}-byte threshold that is supposed to trigger it"
            )
            stubs += 1
    assert stubs > 0, "series_available named keys but no stub was checked"
    assert split_cases > 0, (
        "no case needed a series split, so this test asserted nothing. The threshold is "
        f"{bsd.SERIES_BYTES} bytes; if the evidence genuinely shrank below it, lower the threshold "
        "rather than deleting the test."
    )


# --------------------------------------------------------------------------- derived counts

def test_the_denominators_are_derivable_from_the_artifacts_not_typed(payload: Path):
    """Each of these is re-derived here from a different reading of the same tree. Two numbers
    produced by two paths must be derived twice and compared, never inferred from one another."""
    denominators = read(payload, "denominators.json")
    census = read(payload, "census.json")
    pages = sorted((payload / "cases").glob("*.json"))

    assert denominators["registered"]["n"] == len(pages), (
        "every registered case gets exactly one page, so these cannot differ"
    )
    with_verdict = sum(1 for p in pages if json.loads(p.read_text())["verdict"])
    assert denominators["published"]["n"] == with_verdict
    assert sum(census["verdict_mix"].values()) == with_verdict
    assert "INCONCLUSIVE" in census["verdict_mix"], (
        "INCONCLUSIVE must be its own bucket; folded into either decisive column it becomes a claim "
        "the measurement never made"
    )
    for name, block in denominators.items():
        assert isinstance(block["n"], int)
        assert len(block["definition"]) >= 40, f"{name} has no real definition"
        assert block["derived_from"], f"{name} does not name its source"
    # The four differ for stated reasons; if any two collapsed to one number the reader would have no
    # way to see that they measure different sets.
    assert denominators["registered"]["n"] >= denominators["verdict_eligible"]["n"]
    assert denominators["registered"]["n"] >= denominators["published"]["n"]
    assert denominators["registered"]["n"] >= denominators["claim_mapped"]["n"]


def test_the_seal_is_recomputed_and_not_quoted(payload: Path):
    seal = read(payload, "census.json")["seal"]
    assert seal["registry_sha256_declared"] == seal["registry_sha256_recomputed"]
    assert seal["n_cases_declared"] == len(list((payload / "cases").glob("*.json")))
    assert "read from the sealed register at build time" in seal["method"]


# --------------------------------------------------------------------------- the figure check rc

@pytest.mark.parametrize(("argv_rc", "expected"), [(["--figure-check-rc", "0"], 0),
                                                   (["--figure-check-rc", "1"], 1),
                                                   ([], None)])
def test_figure_check_rc_is_recorded_verbatim_including_not_run(tmp_path, argv_rc, expected):
    """Three states, three renderings: verified / drifted / not verified. The builder must not
    default an omitted check to 0, because that renders an unrun check as verified."""
    out = tmp_path / "payload"
    assert bsd.main(["--out", str(out), "--stamp", "20260101T000000Z", *argv_rc]) == 0
    figures = json.loads((out / "figures.json").read_text(encoding="utf-8"))
    assert figures["numeric_check"] == expected
    assert figures["present"], "no figures were censused, so the pass-through proved nothing"
