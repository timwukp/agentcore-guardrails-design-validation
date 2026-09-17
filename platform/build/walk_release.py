#!/usr/bin/env python3
"""Walk a BUILT release in a real browser, both locales, and read what only the DOM can answer.

WHY THIS IS A FILE AND NOT A ONE-OFF SCRIPT

Every release so far was probed in Chromium before the pointer was flipped, and every one of those
probes was a throwaway script under `/tmp`. The evidence survived (`session-logs/media-walk-*.log`);
the instrument did not. So the run that verified PR #54's explainer cannot be repeated — not because
the method was undocumented, but because `/tmp` is cleared and nobody could state afterwards which
selectors were read or what the thresholds were. A measurement whose instrument is gone is a claim,
and this repository's whole argument is that claims and measurements are different things.

WHAT IT CHECKS, AND WHY EACH ONE NEEDS A BROWSER

  1. **CSP violations, counted at the page.** `check_site_invariants.py` can assert the policy TEXT and
     `csp_preview.py` serves the policy parsed out of the stack, but neither can say a document rendered
     under it without a `Refused to …`. The listener is installed with `add_init_script`, before any of
     the app's own script runs, because a violation fired during the first paint is the one a listener
     attached afterwards cannot see.
  2. **Every `<video>`, read AT THE ELEMENT.** `readyState`, `duration`, `videoWidth/Height`, `error`
     and the caption track's cue count. A `<video>` that decodes nothing renders its poster, and a
     caption track the browser dropped raises no console error: both are silent in every other check
     this repo has. The measured duration is then compared against `media.json`'s `duration_s`, which
     is the payload's own published number — the decoder and the manifest have to agree.
  3. **The four verdict colours, re-measured from `getComputedStyle`.** The stylesheet arm in
     `check_site_invariants.py` reads the SHEET; this reads the SCREEN. Those are different claims, and
     the gap between them is a defect this project has already shipped once: on 2026-08-20 all 38
     diagram boxes rendered in the neutral slate while their class tokens were present in the CSS,
     because a single-class selector later in the file shadowed the rule (`site/src/styles.css:795`). The effective background is resolved by walking ancestors
     until a non-transparent one is found, since `background-color: transparent` on the badge itself is
     what makes the naive reading report 1.00:1 for a perfectly legible chip.

WHAT IT CANNOT CHECK, ON THE RECORD

The **live** CloudFront distribution is not walkable from here: every viewer request is authorized by
a Lambda@Edge Cognito check and the user pool has `mfa: REQUIRED`, so a scripted browser cannot obtain
a session and this platform must never create an account to give it one. What this walks is therefore
the release's own bytes at the release's own URL, served locally by `csp_preview.py` under the CSP
parsed from the stack. The bytes are the published ones (compare the hashes in `MANIFEST.json`); the
network in front of them is not. `publish_web.verify_served()` covers the other half — it re-downloads
what the origin holds and re-runs the redaction patterns over the served bytes — and a human with the
second factor covers the last mile.

USAGE

    python3 platform/build/csp_preview.py --port 8901 &                 # the real CSP
    python3 platform/build/walk_release.py --base http://127.0.0.1:8901
    python3 platform/build/walk_release.py --prefix /v/20260917T091155Z # a stamped build

The interpreter must be the one with `playwright` (`/opt/homebrew/opt/python@3.12/bin/python3.12`),
not `.venv-oracle`, whose botocore pin is a measurement instrument and gets nothing installed into it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

# The route table and the ratio arithmetic are IMPORTED, not restated. Two copies of the WCAG formula
# would let this probe and the stylesheet gate report different ratios for the same pair of colours,
# and two copies of the route list would let a new route fall out of the probe silently — which is the
# defect `census_rendered_surfaces.check_route_tables_agree()` exists to prevent, so it is called here
# too rather than trusted to have been called somewhere else.
import census_rendered_surfaces as census  # noqa: E402
import check_site_invariants as inv  # noqa: E402

DEFAULT_PAYLOAD = REPO.parent / "grx-site-payload"

# Floors, every one of them a collapse detector rather than a target. A walk that found no video, no
# verdict badge or no route is the failure mode this script exists to catch, and all three of them
# otherwise report as a clean run of nothing (`feedback_zero_file_scan_is_error`).
MIN_ROUTES = census.MIN_ROUTES
MIN_VIDEOS_TOTAL = 2          # one per locale on /design; a second chapter raises this
MIN_VERDICTS_SEEN = 4         # TRUE / FALSE / INCONCLUSIVE / RECORDED, each rendered somewhere

# The decoder and the manifest are allowed to disagree by one frame's worth of rounding, not more. At
# 30 fps a frame is 33 ms; 0.05 s leaves room for the container's timescale without leaving room for a
# different file.
DURATION_TOLERANCE_S = 0.05

RGB_RE = re.compile(r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)")

COLLECT_JS = r"""
() => {
  const videos = [...document.querySelectorAll('video')].map(v => {
    const t = v.textTracks && v.textTracks[0];
    return {
      src: (v.currentSrc || v.getAttribute('src') || '').split('/').pop(),
      readyState: v.readyState,
      duration: v.duration,
      videoWidth: v.videoWidth,
      videoHeight: v.videoHeight,
      error: v.error ? v.error.code : null,
      preload: v.preload,
      trackKind: t ? t.kind : null,
      trackLang: t ? t.language : null,
      cues: t && t.cues ? t.cues.length : null,
      firstCue: t && t.cues && t.cues.length ? t.cues[0].text.slice(0, 80) : null,
    };
  });

  // The effective background, not the element's own: a chip declaring `background: transparent`
  // reads as 1.00:1 against itself, which would fail a legible badge and pass an illegible one drawn
  // on a surface that happens to match.
  const effectiveBg = el => {
    for (let n = el; n && n !== document.documentElement; n = n.parentElement) {
      const bg = getComputedStyle(n).backgroundColor;
      if (bg && bg !== 'transparent' && !/rgba\(\s*0\s*,\s*0\s*,\s*0\s*,\s*0\s*\)/.test(bg)) return bg;
    }
    return getComputedStyle(document.body).backgroundColor;
  };

  const badges = {};
  for (const el of document.querySelectorAll('[class*="v-"]')) {
    const token = [...el.classList].find(c => /^v-[A-Z_]+$/.test(c));
    if (!token || badges[token]) continue;
    const cs = getComputedStyle(el);
    if (!el.innerText.trim()) continue;                    // a coloured rule is not a rendered badge
    badges[token] = {colour: cs.color, background: effectiveBg(el),
                     fontSize: cs.fontSize, fontWeight: cs.fontWeight,
                     text: el.innerText.trim().slice(0, 40)};
  }

  return {
    videos,
    badges,
    html_lang: document.documentElement.lang,
    csp: window.__csp || [],
    main_chars: (document.querySelector('main')?.innerText || '').trim().length,
    polly: (document.body.innerText.match(/Amazon Polly[^\n]{0,140}/) || [null])[0],
  };
}
"""


def fail(msg: str) -> None:
    print(f"CANNOT RUN: {msg}", file=sys.stderr)
    raise SystemExit(2)


def hexify(css_colour: str) -> str:
    m = RGB_RE.match(css_colour or "")
    if not m:
        fail(f"cannot read a colour out of {css_colour!r}; getComputedStyle returned a form this "
             "probe does not parse, and guessing one would fabricate a contrast ratio")
    return "#" + "".join(f"{int(v):02x}" for v in m.groups())


def check_server(base: str, prefix: str) -> None:
    url = f"{base}{prefix}/index.html"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            if r.status != 200:
                fail(f"{url} returned HTTP {r.status}")
            if not r.headers.get("Content-Security-Policy"):
                fail(f"{url} was served without a Content-Security-Policy header. Serving the release "
                     "without the policy it will be served under makes every violation below "
                     "unobservable, and zero violations would then read as a pass")
    except (urllib.error.URLError, OSError) as e:
        fail(f"cannot reach {url} ({type(e).__name__}). Start the preview first:\n"
             f"    python3 platform/build/csp_preview.py --port 8901")


def walk(base: str, prefix: str, routes: list[str]) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        fail("playwright is not importable — use the interpreter that has it "
             "(/opt/homebrew/opt/python@3.12/bin/python3.12). This probe measures what a browser "
             "renders and has no source-reading fallback (`feedback_e2e_browser_verification`)")

    out: dict[str, dict] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for locale in census.LOCALES:
                ctx = browser.new_context(locale=locale, viewport={"width": 1440, "height": 1000})
                # Written before any script runs, for the same reason the census does it: clicking the
                # toggle afterwards leaves the first render in the other language, and a violation or a
                # colour collected during that frame belongs to a page the reader never sees.
                ctx.add_init_script(
                    f"try {{ localStorage.setItem('agdv.locale', {json.dumps(locale)}); }} catch (e) {{}}")
                ctx.add_init_script(
                    "document.addEventListener('securitypolicyviolation', e =>"
                    " (window.__csp = window.__csp || []).push("
                    "   e.violatedDirective + ' ' + (e.blockedURI || '') + ' @' + e.sourceFile));")
                page = ctx.new_page()
                console: list[str] = []
                errors: list[str] = []
                page.on("console", lambda m: console.append(f"{m.type}: {m.text}"[:300]))
                page.on("pageerror", lambda e: errors.append(str(e)[:300]))
                for i, route in enumerate(routes):
                    del console[:], errors[:]
                    # A distinct query per route: this is a HashRouter, so changing only the fragment
                    # is not a navigation and `wait_until="load"` would resolve against the previous
                    # document (measured by the census on 2026-09-10).
                    page.goto(f"{base}{prefix}/index.html?walk={i}#{route}", wait_until="load")
                    try:
                        page.wait_for_function(
                            "min => { const m = document.querySelector('main');"
                            " return !!m && m.innerText.trim().length >= min; }",
                            arg=census.MIN_RENDERED_CHARS_PER_ROUTE, timeout=20000)
                    except Exception as e:                        # noqa: BLE001 - reported, not swallowed
                        fail(f"{route} in {locale} never rendered "
                             f"{census.MIN_RENDERED_CHARS_PER_ROUTE} characters of main content "
                             f"within 20 s ({type(e).__name__})")
                    page.wait_for_load_state("networkidle")
                    # `preload` is deliberately not "auto" on the page — the release ships 8 MB of mp4
                    # and a reader who never presses play should not download it — so metadata has to
                    # be asked for here. Without the load() the readyState below is 0 for a video that
                    # is perfectly fine, which is the false negative that makes a probe get ignored.
                    n_videos = page.evaluate("document.querySelectorAll('video').length")
                    if n_videos:
                        page.evaluate("[...document.querySelectorAll('video')].forEach(v => v.load())")
                        try:
                            page.wait_for_function(
                                "() => [...document.querySelectorAll('video')]"
                                ".every(v => v.readyState >= 1 || v.error)", timeout=40000)
                        except Exception as e:                    # noqa: BLE001
                            fail(f"{route} in {locale}: {n_videos} video(s) never reached "
                                 f"readyState 1 or an error within 40 s ({type(e).__name__}) — "
                                 f"neither loaded nor failed is the one state nothing downstream "
                                 f"can interpret")
                        page.wait_for_timeout(800)               # let the caption track parse
                    got = page.evaluate(COLLECT_JS)
                    got["console_errors"] = [m for m in console if m.startswith("error")]
                    got["page_errors"] = list(errors)
                    out[f"{locale} {route}"] = got
                ctx.close()
        finally:
            browser.close()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://127.0.0.1:8901")
    ap.add_argument("--prefix", default="", help="release prefix, e.g. /v/20260917T091155Z")
    ap.add_argument("--payload", type=Path, default=DEFAULT_PAYLOAD)
    args = ap.parse_args(argv)
    prefix = args.prefix.rstrip("/")

    census.check_route_tables_agree()
    routes = list(census.STATIC_ROUTES)
    if len(routes) < MIN_ROUTES:
        fail(f"{len(routes)} route(s) to walk, below the floor of {MIN_ROUTES}")

    media = json.loads((args.payload / "media.json").read_text(encoding="utf-8"))
    declared = {name: t for t in media.get("tracks", []) for name in t["files"]
                if name.endswith(".mp4")}
    verdicts = sorted((json.loads((args.payload / "census.json").read_text(encoding="utf-8"))
                       .get("verdict_mix") or {}))

    check_server(args.base, prefix)
    walked = walk(args.base, prefix, routes)

    problems: list[str] = []
    videos_seen = 0
    badges: dict[str, dict] = {}
    for where, got in sorted(walked.items()):
        locale = where.split(" ")[0]
        if got["csp"]:
            problems.append(f"{where}: CSP violation(s) {got['csp'][:4]}")
        if got["console_errors"]:
            problems.append(f"{where}: console error(s) {got['console_errors'][:3]}")
        if got["page_errors"]:
            problems.append(f"{where}: page error(s) {got['page_errors'][:3]}")
        if got["html_lang"] != locale:
            problems.append(f"{where}: <html lang={got['html_lang']!r}> for a {locale} walk")
        for v in got["videos"]:
            videos_seen += 1
            if v["error"] is not None:
                problems.append(f"{where}: {v['src']} MediaError code {v['error']}")
                continue
            if v["readyState"] < 1 or not v["duration"] or v["duration"] <= 0:
                problems.append(f"{where}: {v['src']} readyState {v['readyState']}, "
                                f"duration {v['duration']}")
            if (v["videoWidth"], v["videoHeight"]) != (1920, 1080):
                problems.append(f"{where}: {v['src']} decoded "
                                f"{v['videoWidth']}x{v['videoHeight']}, not 1920x1080")
            if not v["cues"]:
                problems.append(f"{where}: {v['src']} caption track carries no cues "
                                f"(kind={v['trackKind']}, lang={v['trackLang']})")
            track = declared.get(v["src"])
            if track is None:
                problems.append(f"{where}: the page plays {v['src']}, which media.json does not "
                                f"declare — bytes the payload does not vouch for")
            elif abs(track["duration_s"] - (v["duration"] or 0)) > DURATION_TOLERANCE_S:
                problems.append(f"{where}: {v['src']} decodes to {v['duration']:.3f}s while "
                                f"media.json publishes {track['duration_s']:.3f}s")
            if not got["polly"]:
                problems.append(f"{where}: a video is on the page with no Amazon Polly disclosure "
                                f"in the rendered text")
        badges.update({k: v for k, v in got["badges"].items() if k not in badges})

    if videos_seen < MIN_VIDEOS_TOTAL:
        fail(f"the walk found {videos_seen} video element(s) over {len(routes)} route(s) x "
             f"{len(census.LOCALES)} locale(s), below the floor of {MIN_VIDEOS_TOTAL}. A release whose "
             f"explainer did not render is not a release that passed this probe")

    measured = {}
    for verdict in verdicts:
        seen = badges.get(f"v-{verdict}")
        if not seen:
            problems.append(f"no rendered element carries .v-{verdict} on any walked route, so its "
                            f"colour was never measured on screen")
            continue
        fg, bg = hexify(seen["colour"]), hexify(seen["background"])
        ratio = inv._contrast(fg, bg)                              # noqa: SLF001 - one implementation
        measured[verdict] = {"colour": fg, "background": bg, "ratio": round(ratio, 2),
                             "font_size": seen["fontSize"], "font_weight": seen["fontWeight"],
                             "sample": seen["text"]}
        if ratio < inv.AA_CONTRAST:
            problems.append(f"{verdict} renders {fg} on {bg} = {ratio:.2f}:1, under WCAG 2.1 SC "
                            f"1.4.3's {inv.AA_CONTRAST}:1 for normal text")
    if len(measured) < MIN_VERDICTS_SEEN:
        fail(f"{len(measured)} verdict colour(s) were measured on screen, below the floor of "
             f"{MIN_VERDICTS_SEEN}; the arm reported nothing rather than something wrong")

    report = {
        "base": args.base + (prefix or ""),
        "routes": len(routes), "locales": list(census.LOCALES),
        "videos_read": videos_seen,
        "video_detail": {w: g["videos"] for w, g in sorted(walked.items()) if g["videos"]},
        "verdict_contrast": measured,
        "polly_disclosure": {w: g["polly"] for w, g in sorted(walked.items()) if g["videos"]},
        "csp_violations": {w: g["csp"] for w, g in sorted(walked.items()) if g["csp"]},
        "problems": problems,
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"\nwalked {len(routes)} route(s) x {len(census.LOCALES)} locale(s), read {videos_seen} "
          f"video element(s), measured {len(measured)} verdict colour(s) on screen")
    if problems:
        print(f"PROBLEMS — {len(problems)}")
        for p in problems:
            print(" -", p)
        return 1
    print("OK — zero CSP violations, every video decoded and captioned at the element, every verdict "
          "colour clears AA on the surface it is drawn on")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
