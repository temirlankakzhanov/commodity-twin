"""Optional manual browser check (needs Playwright): nothing covers the hero buttons.

In the pinned scene every layer (hero, closure copy, closure card, console) is stacked in one
frame, so a faded-out layer can sit over the one in view and swallow its clicks. This script
serves ``site/`` locally, opens it in headless Chromium at 1440x900, 1024x800 and 375x812, and
checks that ``elementFromPoint`` at the centre of each hero button returns the button itself (or
one of its children).

Playwright is not a project dependency and this check is not part of ``make check`` or CI.
Run it by hand in a throwaway virtualenv outside the repository, for example::

    python3 -m venv /tmp/pw && /tmp/pw/bin/pip install playwright
    /tmp/pw/bin/python -m playwright install chromium
    make site-assets                      # GSAP, so the pinned scene is built
    /tmp/pw/bin/python scripts/check_hero_hits.py

Exit code 0 when every button is hit, 1 otherwise.
"""

from __future__ import annotations

import functools
import http.server
import sys
import threading
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "site"
SIZES = [(1440, 900), (1024, 800), (375, 812)]

HIT_TEST = """() => [...document.querySelectorAll('.hero-copy .actions a')].map((a) => {
  const r = a.getBoundingClientRect();
  const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return { text: a.textContent.trim(), hit: !!top && (top === a || a.contains(top)),
           top: top ? top.tagName + '.' + String(top.className.baseVal ?? top.className) : null };
})"""


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        """Keep the request log out of the report."""


def serve() -> tuple[http.server.ThreadingHTTPServer, str]:
    """Serve ``site/`` on a free local port in a background thread."""
    handler = functools.partial(_QuietHandler, directory=str(SITE))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def main() -> int:
    """Run the hit test at every size and print one line per button."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed; see the module docstring.", file=sys.stderr)
        return 2
    server, url = serve()
    failures = 0
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for width, height in SIZES:
                page = browser.new_page(viewport={"width": width, "height": height})
                page.goto(url)
                page.wait_for_function("document.documentElement.dataset.story !== undefined")
                page.wait_for_timeout(1500)  # data, fonts and the scene build
                story = page.evaluate("document.documentElement.dataset.story")
                for button in page.evaluate(HIT_TEST):
                    ok = button["hit"]
                    failures += not ok
                    status = "ok" if ok else f"COVERED by {button['top']}"
                    print(f"{width}x{height} ({story}) {button['text']}: {status}")
                page.close()
            browser.close()
    finally:
        server.shutdown()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
