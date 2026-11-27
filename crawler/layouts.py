"""Precompute the viewer's layouts (web/data/layout.json) in headless Chromium.

The page lays out ~2,000 people with d3-dag + sifting, which takes several
seconds in the browser. Running exactly the same code once at build time (via
Playwright) lets the page load the positions instead. Optional: if Playwright
or Chromium is unavailable the page simply computes the layout itself.
"""
import functools
import http.server
import json
import os
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def precompute(log=print, timeout_ms=300000):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("layout precompute skipped (playwright not installed); the page will compute it")
        return False
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=WEB))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/?nolayoutcache" % srv.server_address[1]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(url)
            page.wait_for_selector("g.node", timeout=timeout_ms)
            out = page.evaluate("() => window.__exportLayouts()")
            browser.close()
    except Exception as e:  # keep the build usable without a browser
        log("layout precompute failed (%s); the page will compute it" % str(e).splitlines()[0])
        return False
    finally:
        srv.shutdown()
    path = os.path.join(WEB, "data", "layout.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    log("precomputed layouts: %s (%.1f MB)" % (", ".join(out["views"]), os.path.getsize(path) / 1e6))
    return True
