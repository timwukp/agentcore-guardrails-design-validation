#!/usr/bin/env python3
"""Serve the built SPA behind the response headers CloudFront will actually send.

WHY THIS EXISTS

`platform/infra/test/site-stack.test.ts` can assert the TEXT of the Content-Security-Policy in the
synthesised template. It cannot assert that a browser renders the site under it. Those are different
claims, and the gap between them is a real defect class: a policy that omits `style-src
'unsafe-inline'` synthesises identically, passes every template assertion, and renders an unstyled
page with a console full of violations that nobody reads before deploying.

So the CSP is not re-typed here. It is PARSED OUT of `lib/site-stack.ts` — the same string literal the
stack ships — and a mismatch is impossible by construction rather than by discipline. Change the
policy in the stack, restart this, and the browser sees the change.

USAGE

    python3 platform/build/csp_preview.py            # http://127.0.0.1:8901
    python3 platform/build/csp_preview.py --port 9000 --print-only

`site/dist/data` is expected to be a symlink to the payload directory; the handler follows it, which
is why the payload is reachable at `/data/...` exactly as it will be from the S3 prefix.

WHAT TO CHECK IN THE BROWSER (the part a test cannot do)

  * every route: no `Refused to …` / `Content-Security-Policy` message in the console
  * `[...document.styleSheets].map(s => s.cssRules.length)` — a BLOCKED sheet raises SecurityError
    on `cssRules`, so a number here is proof the stylesheet was applied, not merely fetched
  * `[...document.querySelectorAll('img')].every(i => i.naturalWidth > 0)` — `img-src` blocks show
    up as a zero-width image, not as an exception
"""

from __future__ import annotations

import argparse
import functools
import http.server
import re
import socketserver
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STACK = REPO / "platform" / "infra" / "lib" / "site-stack.ts"
DIST = REPO / "site" / "dist"

# The one place the ResponseHeadersPolicy's non-CSP headers are mirrored. They are simple enough to
# state, and stating them means the preview is not quietly more permissive than production.
STATIC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # Deliberately NOT Strict-Transport-Security: this server is plain HTTP on localhost, and an HSTS
    # header here would pin 127.0.0.1 to HTTPS in the developer's browser for a year.
}


def csp_from_stack(stack: Path = STACK) -> str:
    """Extract the CSP directive list from the stack source.

    Anchored on `contentSecurityPolicy: [` followed by `].join("; ")`, which is the exact shape in
    `site-stack.ts`. If that shape changes this raises instead of falling back to a hardcoded copy —
    a stale preview that silently disagrees with production is worse than no preview.
    """
    src = stack.read_text(encoding="utf-8")
    match = re.search(
        r"contentSecurityPolicy:\s*\[(?P<body>.*?)\]\.join\(\"; \"\)", src, re.DOTALL
    )
    if not match:
        raise SystemExit(
            f"could not find the CSP array literal in {stack}. It is parsed rather than copied on "
            "purpose; if the stack now builds the policy differently, teach this function the new "
            "shape rather than pasting the policy here."
        )
    directives = re.findall(r'"([^"]+)"', match.group("body"))
    if not directives:
        raise SystemExit(f"the CSP array in {stack} parsed to zero directives")
    if not any(d.startswith("default-src") for d in directives):
        raise SystemExit(
            "parsed a CSP with no default-src; refusing to serve a policy that is probably a "
            f"mis-parse of {stack}"
        )
    return "; ".join(directives)


def make_handler(csp: str) -> type[http.server.SimpleHTTPRequestHandler]:
    class Handler(http.server.SimpleHTTPRequestHandler):
        def end_headers(self) -> None:  # noqa: D102 - stdlib override
            self.send_header("Content-Security-Policy", csp)
            for name, value in STATIC_HEADERS.items():
                self.send_header(name, value)
            super().end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            # Only failures. A per-asset access log buries the 404 that matters.
            status = args[1] if len(args) > 1 else ""
            if isinstance(status, str) and status.startswith(("4", "5")):
                sys.stderr.write(f"  {status} {args[0]}\n")

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8901)
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="print the policy parsed from the stack and exit; used by the invariant test",
    )
    args = parser.parse_args(argv)

    csp = csp_from_stack()
    if args.print_only:
        print(csp)
        return 0

    if not (DIST / "index.html").is_file():
        raise SystemExit(f"{DIST}/index.html is missing — run the site build first")
    if not (DIST / "data").exists():
        raise SystemExit(
            f"{DIST}/data does not resolve — vite build removes the symlink, so re-link it to the "
            "payload directory before previewing, or every fetch 404s and the page looks broken for "
            "a reason that has nothing to do with the CSP"
        )

    socketserver.TCPServer.allow_reuse_address = True
    handler = functools.partial(make_handler(csp), directory=str(DIST))
    with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
        print(f"serving {DIST} on http://127.0.0.1:{args.port}")
        print(f"Content-Security-Policy: {csp}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
