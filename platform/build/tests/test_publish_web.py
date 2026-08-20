"""`verify_served` is the last gate in the publish chain, and until 2026-08-20 it had never run.

What it is for
--------------
Every other gate reads the bytes we *meant* to upload. This one downloads the bytes S3 actually holds
and re-runs the redaction patterns over them, which is the only check that can catch a truncated
upload, a mangled object, or a file that reached the bucket without passing through a gate at all.

Why it needed a test
--------------------
The first real release, `v/20260820T073855Z/`, exited 2 here with
`GATE-FAIL: no MANIFEST.json under /var/folders/.../tmpghc_b5ig`. The function synced the whole
release prefix into one directory and passed it to `gate_payload.py --payload`, but `upload()` writes
the payload under `data/` and the SPA at the prefix root — so the manifest was one level down, the
gate refused the tree, and **the redaction patterns never ran over a single served byte.** The
failure was loud, which is the only reason it was not worse; a check that has never executed its own
subject is not a check (`feedback_probe_must_reach_the_code`).

Passing that same combined tree as `--also-scan` instead would have failed in the opposite direction:
`--also-scan` deliberately grants no inherited exceptions, and four RFC1918 hits in
`cases/F5-7b.json` and `findings.json` legitimately inherit one from the artifact they were derived
from. The two halves are scanned under different rules because they *are* different kinds of thing,
so they have to be fetched separately. That is what the first test below pins.

Mutation coverage
-----------------
Run 2026-08-20 against `verify_served`, eight mutants, each with the no-mutant control re-run
afterwards and the file's sha256 asserted back to its pristine value. All eight killed: pre-fix wiring
(whole prefix into one tree); the two halves swapped at the gate; the zero-object guard deleted; set
equality weakened to `len(got) != len(want)`; set equality made one-directional (`want - got`); the
gate step never invoked; `--exclude data/*` dropped from the SPA fetch; the SPA half not compared at
all. Three of those survived the first draft of this file and each survivor named a real hole — see
`test_one_object_swapped_for_another_fails` and `test_an_empty_prefix_fails_rather_than_gating_nothing`,
and the `bucket_keys` docstring below.

`aws` and `run` are substituted rather than reached
---------------------------------------------------
These tests must not make an AWS call or shell out to a gate: the point is the wiring, and a test that
needed credentials would be skipped exactly when it mattered. `aws` is replaced by a fake that
populates the destination directory the way `s3 sync` would, and `run` by one that records the argv it
was handed. The fake honours `--exclude data/*`, because that flag is load-bearing in the real call and
a fake that ignored it would let the wrong wiring pass (`feedback_unreachable_branch_in_fake`).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "platform" / "build"))

import publish_web as pw  # noqa: E402

BUCKET = "grxlive-payload-under-test"
STAMP = "20260820T000000Z"


@pytest.fixture()
def trees(tmp_path):
    """A payload of three files and a dist of three, laid out exactly as `upload()` sends them."""
    payload = tmp_path / "payload"
    (payload / "cases").mkdir(parents=True)
    (payload / "MANIFEST.json").write_text('{"stamp": "x"}\n', encoding="utf-8")
    (payload / "census.json").write_text('{"n": 93}\n', encoding="utf-8")
    (payload / "cases" / "F6-1.json").write_text('{"verdict": "FALSE"}\n', encoding="utf-8")

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html>\n", encoding="utf-8")
    (dist / "assets" / "index-abc.js").write_text("console.log(1)\n", encoding="utf-8")
    (dist / "assets" / "index-abc.css").write_text("body{}\n", encoding="utf-8")
    # The real dist carries a `data` symlink into the payload, and `upload()` excludes it. Present
    # here so the exclusion is exercised rather than assumed.
    (dist / "data").symlink_to(payload, target_is_directory=True)
    return payload, dist


def _listing(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


@pytest.fixture()
def served(monkeypatch, trees):
    """Substitute `aws` and `run`; return the list of what each `run()` was handed.

    Each entry records the argv **and a listing of the two trees as they were at the moment of the
    call**, because `verify_served` fetches into a `TemporaryDirectory` that is deleted before it
    returns. Inspecting the paths afterwards raises `FileNotFoundError`, which is how the first draft
    of this test failed: an assertion about what the gate saw has to be taken while it can still see it.
    """
    payload, dist = trees
    calls: list[dict] = []

    def bucket_keys() -> dict[str, Path]:
        """The objects `upload()` puts under `v/<stamp>/`: the SPA at the root, the payload under `data/`.

        Modelled as ONE flat keyspace rather than as two local trees, because that is what the real
        fetch reads and the difference is load-bearing. A fake that served `dist` for the root prefix
        would hold no `data/` keys, so dropping `--exclude data/*` from the SPA fetch would change
        nothing and the mutant would survive — as it did on 2026-08-20, before this was rewritten
        (`feedback_unreachable_branch_in_fake`).
        """
        keys = {}
        for f in sorted(dist.rglob("*")):
            if f.is_file() and not f.is_symlink():
                keys[str(f.relative_to(dist))] = f
        for f in sorted(payload.rglob("*")):
            if f.is_file() and not f.is_symlink():
                keys[f"data/{f.relative_to(payload)}"] = f
        return keys

    def fake_aws(args, parse_json=True):
        assert args[0] == "s3" and args[1] == "sync", f"unexpected aws call: {args}"
        src, dest = args[2], Path(args[3])
        marker = f"/v/{STAMP}/"
        assert marker in src, f"the fetch is not scoped to the release prefix: {src}"
        prefix = src.split(marker, 1)[1]
        excludes = [args[i + 1] for i, a in enumerate(args) if a == "--exclude"]
        dest.mkdir(parents=True, exist_ok=True)
        for key, source in bucket_keys().items():
            if not key.startswith(prefix):
                continue
            rel = key[len(prefix):]
            if any(fnmatch(rel, pat) for pat in excludes):
                continue
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest / rel)
        return {}

    def fake_run(step, cwd=None):
        argv = [str(a) for a in step.argv]
        seen = {}
        for flag in ("--payload", "--also-scan"):
            root = Path(argv[argv.index(flag) + 1]) if flag in argv else None
            seen[flag] = _listing(root) if root and root.is_dir() else None
        calls.append({"argv": argv, "seen": seen})
        step.rc = 0
        return step

    monkeypatch.setattr(pw, "aws", fake_aws)
    monkeypatch.setattr(pw, "run", fake_run)
    monkeypatch.setattr(pw, "DIST", dist)
    return calls


def _verify(payload: Path) -> None:
    pw.verify_served(pw.Publish(stamp=STAMP, payload=payload), BUCKET)


# --------------------------------------------------------------- 1. the gate reaches the bytes

def test_the_gate_is_pointed_at_the_data_root_and_the_spa_separately(served, trees, capsys):
    payload, _ = trees
    _verify(payload)

    assert len(served) == 1, f"expected exactly one gate invocation, got {served}"
    argv, seen = served[0]["argv"], served[0]["seen"]
    assert argv[1].endswith("gate_payload.py"), argv
    scanned, also = seen["--payload"], seen["--also-scan"]

    assert scanned is not None and also is not None, (
        f"the gate was not handed both halves of the release: {argv}")
    assert "MANIFEST.json" in scanned, (
        "--payload does not point at the directory holding MANIFEST.json, so gate_payload.py will "
        f"refuse the tree and the patterns will not run over any served byte. It held {scanned}")
    assert "cases/F6-1.json" in scanned, scanned
    assert "MANIFEST.json" not in also, (
        "the SPA tree handed to --also-scan contains the payload. --also-scan grants no inherited "
        f"exceptions, so the reviewed RFC1918 hits in cases/F5-7b.json would be convicted. It held {also}")
    assert "index.html" in also and "assets/index-abc.js" in also, (
        f"--also-scan does not point at the built SPA. It held {also}")

    out = capsys.readouterr().out
    assert "3 payload object(s)" in out and "3 SPA object(s)" in out, out


# --------------------------------------------------------------- 2. set equality, both directions

def _after_sync(monkeypatch, mangle):
    """Wrap the fake sync so `mangle(dest)` runs on the bucket copy, leaving the local tree intact.

    The divergence has to be introduced on the DOWNLOADED side. Deleting from the payload instead
    would change both sides at once — the fake reads the tree at call time — and the two sets would
    still be equal, which is a test that cannot fail.
    """
    inner = pw.aws

    def wrapper(args, parse_json=True):
        result = inner(args, parse_json)
        mangle(Path(args[3]))
        return result

    monkeypatch.setattr(pw, "aws", wrapper)


def test_a_missing_object_in_the_bucket_fails(served, trees, monkeypatch):
    """A truncated upload: the bucket holds less than was built."""
    payload, _ = trees
    _after_sync(monkeypatch, lambda dest: (dest / "census.json").unlink(missing_ok=True))
    with pytest.raises(SystemExit) as exc:
        _verify(payload)
    assert exc.value.code == 2


def test_an_extra_object_in_the_bucket_fails(served, trees, monkeypatch):
    """The half a count cannot catch: one missing and one extra is the same integer.

    This arm is what makes the check about identity rather than size, and a leftover object from an
    interrupted publish is exactly this shape.
    """
    payload, _ = trees

    def add_leftover(dest: Path) -> None:
        if (dest / "MANIFEST.json").exists():        # the payload half only
            (dest / "leftover-from-a-previous-release.json").write_text("{}\n", encoding="utf-8")

    _after_sync(monkeypatch, add_leftover)
    with pytest.raises(SystemExit) as exc:
        _verify(payload)
    assert exc.value.code == 2


def test_one_object_swapped_for_another_fails(served, trees, monkeypatch):
    """One missing and one extra is the same integer, and this is the only arm that says so.

    The two arms above both change the object *count*, so both of them would still pass if the check
    were weakened from set equality to `len(got) != len(want)` — verified by mutation on 2026-08-20,
    where exactly that mutant survived the first version of this file. A swap is what a re-published
    release with a renamed asset looks like, and it is invisible to a count.
    """
    payload, _ = trees

    def swap(dest: Path) -> None:
        if (dest / "census.json").exists():
            (dest / "census.json").unlink()
            (dest / "census-v2.json").write_text('{"n": 93}\n', encoding="utf-8")

    _after_sync(monkeypatch, swap)
    with pytest.raises(SystemExit) as exc:
        _verify(payload)
    assert exc.value.code == 2


def test_an_empty_prefix_fails_rather_than_gating_nothing(served, trees):
    """Zero objects must be an error, not a pass over an empty set (`feedback_zero_file_scan_is_error`).

    Both trees are emptied, which is the *only* state set equality cannot catch: empty equals empty,
    so the gate would be handed nothing, find nothing, and report clean. Emptying only the bucket side
    would be caught by the set comparison instead, and this arm would then be testing that — which is
    how it went vacuous the first time (the `if not got` guard could be deleted with all five tests
    still green).
    """
    payload, dist = trees
    for tree in (payload, dist):
        for f in sorted(tree.rglob("*"), reverse=True):
            if f.is_file() and not f.is_symlink():
                f.unlink()
    with pytest.raises(SystemExit) as exc:
        _verify(payload)
    assert exc.value.code == 2


def test_the_unmutated_trees_pass(served, trees):
    """The no-mutant control. Without it, every arm above would also pass if `verify_served` had
    started raising unconditionally."""
    payload, _ = trees
    _verify(payload)            # must not raise
    assert len(served) == 1


# ---------------------------------------------------------------------------- the curation gates
#
# `CURATION_GATES` exists because a conditional gate fails SILENTLY. Its condition is the presence of a
# payload file, so renaming either side — the emitted file or the check — stops the branch firing and
# the publish then reports a clean run with one fewer gate. That is indistinguishable, in the record and
# on the screen, from a run that passed it (`feedback_missing_check_is_not_pass`). These arms walk the
# table in both directions so a rename fails a test instead of quietly widening what may be published.


def _fake_gate_run(monkeypatch) -> list[list[str]]:
    """Record what `gate_payload` would execute instead of executing it.

    Only `run` is faked. `fail` still raises, and the presence checks still hit the real filesystem —
    those are the two behaviours under test, and a fake that swallowed either would make every arm here
    vacuous (`feedback_unreachable_branch_in_fake`).
    """
    argvs: list[list[str]] = []

    def fake_run(step, cwd=None):
        argvs.append([str(a) for a in step.argv])
        step.rc = 0
        return step

    monkeypatch.setattr(pw, "run", fake_run)
    return argvs


def _curation_only(pub_payload: Path, present: list[str]) -> None:
    for name in present:
        (pub_payload / name).write_text("{}\n", encoding="utf-8")


def _gates_for(monkeypatch, tmp_path, present: list[str], tag: str = "a"):
    """Run only the curation-gate loop of `gate_payload`, with `present` payload files in place."""
    payload = tmp_path / f"curation-payload-{tag}"
    payload.mkdir()
    _curation_only(payload, present)
    pub = pw.Publish(stamp=STAMP, payload=payload)
    argvs = _fake_gate_run(monkeypatch)
    for gate in pw.CURATION_GATES:
        script = pw.REPO / "platform" / "build" / gate["script"]
        if not (pub.payload / gate["emits"]).exists():
            pw.skip(pub, gate["name"], f"the payload contains no {gate['emits']} ({gate['absent']})")
            continue
        if not script.is_file():
            pw.fail(f"the payload contains {gate['emits']} but platform/build/{gate['script']} does "
                    f"not exist. {gate['ungated_means']}")
        pub.steps.append(pw.run(pw.Step(gate["name"], [str(pw.VENV_ORACLE), str(script), *gate["args"]])))
    return pub, argvs


def test_no_entry_is_half_built_in_the_direction_that_publishes_ungated():
    """The pairing invariant: authored curation ⇒ its gate exists.

    A table entry may legitimately name a script nobody has written — `check_scenarios.py` does not
    exist today, and the lens it would gate has not been authored either. That combination is honest:
    the payload carries no `scenarios.json`, so the loop skips and records the skip.

    The combination that must never exist is the other one: a curation file a human HAS authored whose
    gate is missing. The publish then refuses every time, which is loud — but the arm exists because the
    obvious "fix" for a refusal is to delete the table entry, and that is the change that publishes the
    curation with nothing checking it. Asserting the pairing here means the deletion fails a test rather
    than clearing a blocker.
    """
    for gate in pw.CURATION_GATES:
        authored = (pw.REPO / gate["curation"]).is_file()
        exists = (pw.REPO / "platform" / "build" / gate["script"]).is_file()
        if authored:
            assert exists, (
                f"{gate['curation']} is authored but platform/build/{gate['script']} does not exist. "
                f"Write the check — do not remove the entry."
            )
        assert gate["ungated_means"].strip() and gate["absent"].strip(), (
            f"{gate['name']} states no consequence for running ungated, or no reason for being absent; "
            f"an unexplained gate is one somebody removes."
        )


@pytest.fixture(scope="module")
def built_payload(tmp_path_factory) -> Path:
    """A REAL payload from `build_site_data.py`, run as a subprocess.

    Deliberately not an import: this file's subject is `publish_web`, and the arm below asks whether the
    two programs agree on a filename. Loading the builder in-process to answer that would put both
    halves of the agreement inside one interpreter, where a shared constant could satisfy the assertion
    without the file ever being written. The subprocess boundary is the point — the evidence is the
    payload on disk.
    """
    out = tmp_path_factory.mktemp("real-payload") / "payload"
    proc = subprocess.run([sys.executable, str(REPO / "platform" / "build" / "build_site_data.py"),
                           "--out", str(out), "--stamp", STAMP, "--figure-check-rc", "0"],
                          cwd=REPO, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"the builder exited {proc.returncode}: {proc.stderr[-600:]}"
    return out


def test_an_authored_curation_file_reaches_the_payload_and_the_gate(monkeypatch, tmp_path,
                                                                    built_payload):
    """The direction that catches a rename. For every curation file a human HAS authored, the real
    build must emit the payload file the gate keys on, and the gate must then run.

    This is the arm that fails if `build_site_data.py` emits the inventory as `control_inventory.json`
    while the table still waits for `controls.json`: nothing else in this repository would notice, and
    the publish would go out with the citation rules unenforced.
    """
    authored = [g for g in pw.CURATION_GATES if (pw.REPO / g["curation"]).is_file()]
    assert authored, "no curation file is authored yet; this arm would be vacuous"
    for gate in authored:
        assert (built_payload / gate["emits"]).is_file(), (
            f"{gate['curation']} is authored but the build emitted no {gate['emits']}, so the "
            f"{gate['name']} never runs and the publish looks clean without it."
        )
    pub, argvs = _gates_for(monkeypatch, tmp_path, [g["emits"] for g in authored])
    ran = {" ".join(a) for a in argvs}
    for gate in authored:
        assert any(gate["script"] in a for a in ran), f"{gate['name']} did not run"
        for extra in gate["args"]:
            assert any(extra in a for a in ran), (
                f"{gate['name']} ran without {extra}, which is the flag that makes it re-derive rather "
                f"than trust its authored input."
            )
    assert pub.skipped == [] or all(s["name"] not in {g["name"] for g in authored}
                                   for s in pub.skipped)


def test_a_payload_file_with_no_gate_script_refuses_to_publish(monkeypatch, tmp_path):
    """The mutation: the payload carries the authored curation, the check has been deleted. Publishing
    it ungated must be impossible, not merely inadvisable."""
    victim = pw.CURATION_GATES[-1]
    real = pw.REPO / "platform" / "build" / victim["script"]
    moved = real.with_suffix(".py.hidden-by-test")
    real.rename(moved)
    try:
        with pytest.raises(SystemExit) as exc:
            _gates_for(monkeypatch, tmp_path, [victim["emits"]], tag="mutant")
        assert exc.value.code == 2
    finally:
        moved.rename(real)
    # The no-mutant control, in the same arm: with the script back, the same payload passes.
    pub, argvs = _gates_for(monkeypatch, tmp_path, [victim["emits"]], tag="control")
    assert any(victim["script"] in " ".join(a) for a in argvs)


def test_a_skipped_gate_is_recorded_rather_than_only_printed(monkeypatch, tmp_path, capsys):
    """A gate that did not run is a fact about the release. `current.json` carries `gates_skipped`
    because a reader comparing two releases has no other way to tell that one of them enforced less."""
    pub, argvs = _gates_for(monkeypatch, tmp_path, present=[])
    assert argvs == [], "no curation file was present, so no gate should have run"
    assert [s["name"] for s in pub.skipped] == [g["name"] for g in pw.CURATION_GATES]
    for entry in pub.skipped:
        assert entry["why"].strip(), "a skip with no reason is the one somebody makes permanent"
    assert "skipped" in capsys.readouterr().out
