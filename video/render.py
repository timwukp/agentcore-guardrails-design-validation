"""Render the explainer videos: script + payload in, mp4/vtt/RENDER.json out.

    /opt/homebrew/opt/python@3.12/bin/python3.12 video/render.py                    # all four, both languages
    /opt/homebrew/opt/python@3.12/bin/python3.12 video/render.py --verify           # render TWICE, demand identical bytes
    /opt/homebrew/opt/python@3.12/bin/python3.12 video/render.py --video before     # one chapter, for iterating

Four videos: the `overview`, and one chapter per phase (`before`, `during`, `after`). The set is
`script/*.yaml`, never a list — see `all_videos()`. A full run renders them against ONE payload
snapshot, so the numbers they speak cannot disagree with each other.

THE PIPELINE, AND WHAT EACH STEP MEASURES RATHER THAN ASSUMES

  script yaml ──resolve {placeholders} from the payload──► spoken text (also the VTT text, verbatim)
      │                                                        │
      │                                   aws polly synthesize-speech (en: Ruth/generative,
      │                                   zh: Zhiyu/neural cmn-CN — Polly has NO zh-TW voice)
      │                                                        │
      │                                        mp3 per scene; duration MEASURED with ffprobe —
      │                                        frame timings derive from the measurement, never
      │                                        from a target the narration was supposed to hit
      │                                                        │
  scenes.py ──Chromium screenshot per scene step──► PNG frames, timed to the scene's own audio
      │                                                        │
      └──► ffmpeg THREE times: video-only libx264, audio-only aac, then a `-c copy` remux of the
           two finished files (see render_language — one combined call does not reproduce)
                             ──► media/<video>.<lang>.mp4  +  media/<video>.<lang>.vtt

DETERMINISM IS ASSERTED, NOT ASSUMED. `--verify` runs the whole pipeline twice — synthesis
included — into two separate trees and requires every output's sha256 to match, then records the
outcome in RENDER.json. Measured on this machine before this pipeline was trusted: Polly returns
byte-identical mp3 for identical (text, voice, engine) on both engines; Chromium screenshots are
byte-identical across launches; and each SINGLE-STREAM ffmpeg stage is byte-identical under the
flags below. A single combined mux is NOT — that is what the three-call structure is for, and the
measurement behind it is written out where the calls are.

The caveat that stays true anyway: byte-reproducibility is MACHINE-scoped — the frames rasterize
whatever Helvetica and PingFang TC this Mac ships — so RENDER.json records the platform string
beside the hashes rather than implying a portable proof.

WHY THE OUTPUTS LIVE UNDER video/out/ (GITIGNORED), NOT IN THE REPOSITORY

The mp4s are tens of megabytes of derived bytes. The repo carries what derives them (this file,
`scenes.py`, the script yaml); the payload carries the bytes, copied and hashed by
`build_site_data.copy_media()` exactly as the whitepaper figures are; and RENDER.json carries the
provenance the copy declares. Committing the mp4s would put the one artifact nobody can review in
the one place everything is reviewed.

Cost, disclosed: narration is billed per character per synthesis, and `--verify` synthesizes
everything twice. Counted from the four scripts with the payload's own values substituted in
(2026-09-18): one render pass is 10,576 English characters on the generative engine and 3,856 Chinese
on neural, so a `--verify` bills 21,152 generative and 7,712 neural — the two engines are priced
differently, which is why the two are counted separately rather than added. The MEASURED meter figure
is in `video/README.md`; the count here is of what is sent, and the meter is the only thing that says
what was charged (`feedback_meter_not_artifact` — a cache made an earlier reading of this pipeline
look six times cheaper than the bill).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import scenes as scenes_mod  # noqa: E402

DEFAULT_PAYLOAD = Path.home() / "Downloads" / "grx-site-payload"
OUT = HERE / "out"

PAYLOAD_FILES = ("census.json", "denominators.json", "practices.json", "architecture.json")

VOICE = {
    "en": {"voice": "Ruth", "engine": "generative", "language": "en-US"},
    # Polly ships no zh-TW voice at all (verified against `describe-voices` 2026-09-15, and again
    # here every run: synthesize fails loudly if the voice/engine pair stops existing). Zhiyu is
    # Mainland Mandarin on the neural engine — the page, the payload and the closing narration all
    # say so, because claiming 真人發聲 or 台灣華語 over this track would be this platform
    # contradicting its own editorial rule.
    "zh": {"voice": "Zhiyu", "engine": "neural", "language": "cmn-CN"},
}

FFMPEG_BITEXACT = ["-map_metadata", "-1", "-fflags", "+bitexact",
                   "-flags:v", "+bitexact", "-flags:a", "+bitexact"]


def die(msg: str) -> None:
    raise SystemExit(f"FATAL: {msg}")


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(cmd: list[str], attempts: int = 1, label: str = "") -> None:
    """`attempts > 1` retries with backoff — for the network calls only.

    A full `--verify` is two renders, ~20 synthesis calls and 12 ffmpeg invocations, tens of minutes.
    The first attempt at it died on `Read timeout on endpoint URL: …polly.us-east-1…` after verify-a
    had completed every file — a single transient HTTP timeout discarding a completed arm's work and,
    worse, reporting rc 1 for something that says nothing about determinism. ffmpeg gets no retry: it
    reads local files, so a failure there is a real one and repeating it only hides which.
    """
    last = ""
    for attempt in range(1, attempts + 1):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            return
        last = f"{cmd[0]} rc {r.returncode}: {r.stderr.strip()[:800]}"
        if attempt < attempts:
            wait = 5 * (3 ** (attempt - 1))  # 5s, 15s, 45s
            print(f"  retry {attempt}/{attempts - 1} in {wait}s — {label or cmd[0]}: {last[:160]}",
                  flush=True)
            time.sleep(wait)
    die(last)


def load_payload(payload_dir: Path) -> tuple[dict, dict[str, str]]:
    data, hashes = {}, {}
    for name in PAYLOAD_FILES:
        p = payload_dir / name
        if not p.is_file():
            die(f"{p} is missing; the scenes may only draw what the site serves")
        hashes[name] = sha256_file(p)
        data[name.removesuffix(".json")] = json.loads(p.read_text(encoding="utf-8"))
    return data, hashes


def load_script(video: str) -> tuple[dict, str]:
    p = HERE / "script" / f"{video}.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    if doc.get("video") != video:
        die(f"{p} declares video={doc.get('video')!r}, expected {video!r}")
    return doc, sha256_file(p)


def all_videos() -> list[str]:
    """Every video there is, DERIVED from `script/*.yaml` rather than listed here.

    `build_site_data.derive_media()` and `check_site_invariants.arm_media` already derive the expected
    media set from the same glob. A list written in this file would be a third declaration of the same
    membership, and the way it fails is the quiet one: a new chapter script renders nothing, the gate
    reports its four files missing, and the renderer — the only component that could have produced
    them — reports success.
    """
    names = sorted(p.stem for p in (HERE / "script").glob("*.yaml"))
    if not names:
        die(f"no scripts under {HERE / 'script'}; there is nothing to render")
    return names


def resolve_text(template: str, values: dict[str, int]) -> str:
    """Fill `{placeholders}`, then refuse any that survived — a `{n_typo}` spoken aloud as a brace
    literal is a defect the soundtrack cannot flag."""
    text = template.format_map(values)
    left = re.findall(r"\{[a-z_]+\}", text)
    if left:
        die(f"unresolved placeholder(s) {left} in narration: {text[:80]}…")
    return " ".join(text.split())


def synthesize(text: str, lang: str, cache: Path) -> Path:
    v = VOICE[lang]
    key = hashlib.sha256(f"{v['voice']}|{v['engine']}|{v['language']}|{text}".encode()).hexdigest()
    mp3 = cache / f"{key}.mp3"
    if mp3.is_file() and mp3.stat().st_size > 0:
        return mp3
    cache.mkdir(parents=True, exist_ok=True)
    cmd = ["aws", "polly", "synthesize-speech", "--region", "us-east-1",
           "--engine", v["engine"], "--voice-id", v["voice"],
           "--output-format", "mp3", "--text", text]
    if v["language"] != "en-US":
        cmd += ["--language-code", v["language"]]
    # Synthesized to a `.part` and renamed only on success. The cache key is the REQUEST, not the
    # bytes, so a half-downloaded mp3 left behind by a timeout would be served as a cache hit on the
    # next run and muxed as a truncated narration — which sounds like an editing decision, not a
    # failure. The rename is the commit.
    part = cache / f"{key}.part"
    part.unlink(missing_ok=True)
    cmd.append(str(part))  # the CLI's output file is positional and must stay last
    run(cmd, attempts=4, label=f"polly {lang}")
    if not part.is_file() or part.stat().st_size == 0:
        die(f"polly wrote no bytes for a {lang} scene — an empty mp3 muxes into silence, not an error")
    part.rename(mp3)
    return mp3


def duration_s(media: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(media)], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        die(f"ffprobe could not measure {media}")
    return float(r.stdout.strip())


def vtt_stamp(t: float) -> str:
    ms = round(t * 1000)
    return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d}.{ms % 1000:03d}"


def render_language(video: str, lang: str, payload: dict, script: dict,
                    values: dict[str, int], work: Path) -> dict:
    """One language's full render into `work`; returns the manifest entry for its two files."""
    from playwright.sync_api import sync_playwright

    built = scenes_mod.scenes(payload, lang, video)
    by_id = {sid: steps for sid, steps in built}
    script_ids = [s["id"] for s in script["scenes"]]
    if script_ids != [sid for sid, _ in built]:
        die(f"scene ids disagree: script {script_ids} vs scenes.py {[s for s, _ in built]} — "
            f"narration and frames would silently pair up wrong")

    # Namespaced by VIDEO as well as language: the chapters reuse scene ids (`title`, `verify`) on
    # purpose, so a per-language directory would have four videos writing `title-00.png` over each
    # other and the concat list would point at whichever render finished last.
    frames_dir = work / "frames" / video / lang
    frames_dir.mkdir(parents=True, exist_ok=True)
    audio_cache = OUT / "audio"

    rows = []  # per scene: (resolved text, mp3 path, duration, [frame paths])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": scenes_mod.WIDTH, "height": scenes_mod.HEIGHT},
                                device_scale_factor=1)
        for sc in script["scenes"]:
            text = resolve_text(sc[lang if lang in sc else "en"], values)
            mp3 = synthesize(text, lang, audio_cache)
            dur = duration_s(mp3)
            frame_paths = []
            for i, html in enumerate(by_id[sc["id"]]):
                page.set_content(html)
                page.wait_for_timeout(250)
                fp = frames_dir / f"{sc['id']}-{i:02d}.png"
                page.screenshot(path=str(fp))
                frame_paths.append(fp)
            rows.append((text, mp3, dur, frame_paths))
        browser.close()

    # concat demuxer lists. The video list times each scene's steps to that scene's own measured
    # audio, the last step absorbing the rounding; the demuxer wants the final frame repeated once.
    flist, alist, vtt, t = [], [], ["WEBVTT", ""], 0.0
    for text, mp3, dur, frame_paths in rows:
        step = dur / len(frame_paths)
        for fp in frame_paths:
            flist += [f"file '{fp}'", f"duration {step:.3f}"]
        alist.append(f"file '{mp3}'")
        vtt += [f"{vtt_stamp(t)} --> {vtt_stamp(t + dur)}", text, ""]
        t += dur
    flist.append(f"file '{rows[-1][3][-1]}'")
    (work / f"frames-{video}-{lang}.txt").write_text("\n".join(flist) + "\n", encoding="utf-8")
    (work / f"audio-{video}-{lang}.txt").write_text("\n".join(alist) + "\n", encoding="utf-8")

    media = work / "media"
    media.mkdir(parents=True, exist_ok=True)
    mp4 = media / f"{video}.{lang}.mp4"
    vtt_path = media / f"{video}.{lang}.vtt"
    vtt_path.write_text("\n".join(vtt), encoding="utf-8")

    # THREE ffmpeg calls, not one, and the reason is measured rather than stylistic.
    #
    # Muxing both streams in a single call is NOT byte-reproducible. Measured 2026-09-16 on this
    # machine: three runs over byte-identical frames and mp3s produced three different files, and an
    # atom-level diff located the whole difference in `stsc` and `stco` — sample-to-chunk and chunk
    # offsets. Every byte of `mdat`, and `stsz`/`stts`/`stss` with it, was identical. So the media
    # content never drifted; the muxer merely grouped the same samples into different chunks, because
    # its interleaver flushes on whatever a packet-producing encoder has handed it at that moment, and
    # that is wall-clock dependent. `-max_interleave_delta 0` does not fix it (three more runs, three
    # more hashes).
    #
    # Each single-stream stage IS reproducible, and each was measured separately: video-only encode
    # identical across runs, audio-only 3/3 identical, `-c copy` remux of two finished files 3/3
    # identical. With both inputs complete on disk, the interleaver's decisions follow from
    # timestamps alone, and there is no encoder timing left to depend on.
    #
    # This corrects the earlier note in this file's docstring, which claimed ffmpeg was byte-identical
    # under these flags. The smoke test behind that claim muxed a single stream and so never exercised
    # the interleaver — the flags were never the whole story, and the gap was in what was measured.
    v_only = work / f"video-{video}-{lang}.mp4"
    a_only = work / f"audio-{video}-{lang}.m4a"
    run(["ffmpeg", "-y", "-v", "error",
         "-f", "concat", "-safe", "0", "-i", str(work / f"frames-{video}-{lang}.txt"), "-an",
         "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-r", "30",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", str(v_only)])
    run(["ffmpeg", "-y", "-v", "error",
         "-f", "concat", "-safe", "0", "-i", str(work / f"audio-{video}-{lang}.txt"), "-vn",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
         "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact", str(a_only)])
    run(["ffmpeg", "-y", "-v", "error", "-i", str(v_only), "-i", str(a_only),
         "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-shortest",
         "-movflags", "+faststart", *FFMPEG_BITEXACT, str(mp4)])

    v = VOICE[lang]
    return {
        "video": video,
        "language": lang, "voice": v["voice"], "engine": v["engine"],
        "voice_language": v["language"], "synthesized": True,
        "duration_s": round(duration_s(mp4), 3), "n_scenes": len(rows),
        "files": {mp4.name: {"bytes": mp4.stat().st_size, "sha256": sha256_file(mp4)},
                  vtt_path.name: {"bytes": vtt_path.stat().st_size, "sha256": sha256_file(vtt_path)}},
    }


def render_all(videos: list[str], payload_dir: Path, work: Path) -> dict:
    """Every requested video against ONE payload snapshot, into one manifest.

    One snapshot is the point of rendering them together. Four videos rendered on four days would
    each be internally consistent and collectively lie: the overview would speak one case count and
    a chapter another, both truthfully as of their own render, with nothing in the payload able to
    tell them apart. `payload_inputs` is therefore hashed once, here, and covers every track below
    it.
    """
    payload, input_hashes = load_payload(payload_dir)
    values = scenes_mod.resolve(payload)
    tracks, script_shas = [], {}
    for video in videos:
        script, script_shas[video] = load_script(video)
        print(f"  {video}: {len(script['scenes'])} scene(s)", flush=True)
        tracks += [render_language(video, lang, payload, script, values, work)
                   for lang in ("en", "zh")]
    return {"videos": videos, "script_sha256": script_shas, "payload_inputs": input_hashes,
            "resolved_values": values, "platform": platform.platform(), "tracks": tracks}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--video", default="all",
                    help="a script stem (overview, before, during, after) or `all` — the default, "
                         "because the payload snapshot is per-RUN and a partial render leaves the "
                         "manifest describing one video while the payload expects four")
    ap.add_argument("--payload", type=Path, default=DEFAULT_PAYLOAD)
    ap.add_argument("--verify", action="store_true",
                    help="render twice into separate trees (fresh synthesis included) and require "
                         "every output byte-identical before publishing the result")
    args = ap.parse_args(argv)
    videos = all_videos() if args.video == "all" else [args.video]
    unknown = [v for v in videos if not (HERE / "script" / f"{v}.yaml").is_file()]
    if unknown:
        die(f"no script for {unknown}; known videos: {all_videos()}")

    if args.verify:
        m1 = render_all(videos, args.payload, OUT / "verify-a")
        shutil.rmtree(OUT / "audio", ignore_errors=True)  # force a second synthesis
        m2 = render_all(videos, args.payload, OUT / "verify-b")
        # Compared by (video, language, file name), not by list position: zip over two track lists
        # would pair up silently if a render ever emitted them in a different order, and the failure
        # it produces — "the two renders disagree" — would be a lie about the very property being
        # measured.
        a = {(t["video"], t["language"], name): f["sha256"]
             for t in m1["tracks"] for name, f in t["files"].items()}
        b = {(t["video"], t["language"], name): f["sha256"]
             for t in m2["tracks"] for name, f in t["files"].items()}
        if set(a) != set(b):
            die(f"the two renders produced different file sets: only in A {sorted(set(a) - set(b))}, "
                f"only in B {sorted(set(b) - set(a))}")
        mismatched = [k for k in sorted(a) if a[k] != b[k]]
        if mismatched:
            die(f"the two renders disagree on {mismatched}; a pipeline whose output drifts "
                f"cannot be hash-verified and must not be published")
        for name in ("media", "frames"):
            dst = OUT / name
            shutil.rmtree(dst, ignore_errors=True)
            shutil.move(str(OUT / "verify-b" / name), str(dst))
        shutil.rmtree(OUT / "verify-a")
        shutil.rmtree(OUT / "verify-b")
        m2["verified_identical_renders"] = True
        manifest = m2
    else:
        manifest = render_all(videos, args.payload, OUT)
        manifest["verified_identical_renders"] = False

    out = OUT / "media" / "RENDER.json"
    out.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    total = sum(t["duration_s"] for t in manifest["tracks"])
    print(f"rendered {', '.join(manifest['videos'])}: {len(manifest['tracks'])} track(s), "
          f"{total:.0f}s total, verified={manifest['verified_identical_renders']}")
    for t in manifest["tracks"]:
        print(f"  {t['video']:9} {t['language']}  {t['duration_s']:7.1f}s  "
              f"{t['n_scenes']:2} scenes  {t['voice']}/{t['engine']}")
    print(f"manifest -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
