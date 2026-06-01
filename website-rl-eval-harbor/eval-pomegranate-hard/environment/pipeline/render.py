"""Deterministic screenshot rendering for the website-replication pipeline.

THE SINGLE RENDERING PATH
-------------------------
Every screenshot the pipeline ever produces — the reference render of a
generated site *and* the render of the coding agent's reconstructed output —
flows through this module, through the **same** browser context built by
``_new_context`` from the **same** module-level constants. There is
deliberately no second code path and no per-caller config knob that could let
reference and agent renders diverge. That render parity is the whole point: any
difference between how we capture the two sides is pure noise injected straight
into the grader's reward signal (see decisions.md / D3).

If you need to change *how* pages are rendered, change a constant here. Do not
add an alternate capture function for one side of the comparison.

WHAT "DETERMINISTIC" MEANS HERE
-------------------------------
Re-rendering the *same* HTML on the *same* machine yields **pixel-identical**
PNGs. We get there by removing every source of nondeterminism we can:

  * fixed viewport width (1280) and device scale factor (1)
  * site served over a local static HTTP server (so relative asset paths and
    inter-page links resolve exactly as a browser expects — never ``file://``)
  * settle before capture: network idle, ``document.fonts.ready``, every
    ``<img>`` ``complete``
  * all animation/transition disabled via injected CSS + ``prefers-reduced-motion``
  * scrollbar hidden so it can't perturb layout width
  * locale + timezone pinned
  * a hard offline guard: any request to a non-local origin is aborted and
    recorded (a site reaching the network is itself a determinism bug)

Cross-platform note: text rasterization differs between macOS and Linux, so a
mac render and a container render of the same page are *not* guaranteed to be
byte-identical. That is fine and expected — the grader always renders BOTH the
reference and the agent output on the *same* platform (the Ubuntu grading
container), so the only determinism we rely on is same-machine determinism,
which this module guarantees. This file runs on both macOS (dev) and Ubuntu
(grading); see ``LAUNCH_ARGS``.

Public API
----------
    capture_page(url_or_file, output_path) -> CaptureResult
    capture_site(site_dir, output_dir, pages=None) -> dict[str, Path]
"""

from __future__ import annotations

import json
import logging
import struct
import threading
from dataclasses import dataclass, field
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from playwright.sync_api import sync_playwright

log = logging.getLogger("pipeline.render")

# --------------------------------------------------------------------------- #
# Render config — the single source of truth. Changing a value here changes it
# identically for the reference render and the agent render. Nothing below
# accepts a per-call override of these; that is intentional (render parity).
# --------------------------------------------------------------------------- #

VIEWPORT_WIDTH = 1280
# Initial viewport height; full-page capture flows past it to the full scroll
# height, so this only sets the starting layout viewport.
VIEWPORT_HEIGHT = 800
# 1 device px == 1 CSS px. Kept at 1 (not 2/"retina") so PNG dimensions equal
# CSS pixels and renders stay comparable across machines with different DPRs.
DEVICE_SCALE_FACTOR = 1

LOCALE = "en-US"
TIMEZONE_ID = "UTC"
COLOR_SCHEME = "light"
REDUCED_MOTION = "reduce"

NAV_TIMEOUT_MS = 30_000
SETTLE_TIMEOUT_MS = 20_000

# Origins the offline guard permits. Everything else is aborted + recorded.
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})

# Injected as early as possible on every frame (see _INIT_SCRIPT) AND re-applied
# after load. Kills animation/transition (so capture timing can't change pixels),
# pins the caret invisible, and hides the scrollbar (so it can't steal layout
# width). No layout/spacing changes beyond the scrollbar — we must not alter the
# design we are trying to faithfully capture.
DISABLE_MOTION_CSS = (
    "*,*::before,*::after{"
    "animation:none!important;"
    "animation-duration:0s!important;"
    "animation-delay:0s!important;"
    "transition:none!important;"
    "transition-duration:0s!important;"
    "transition-delay:0s!important;"
    "scroll-behavior:auto!important;"
    "caret-color:transparent!important;"
    "}"
    "html{scrollbar-width:none!important;}"
    "::-webkit-scrollbar{width:0!important;height:0!important;display:none!important;}"
)

# Runs before page scripts on every navigation. documentElement exists this
# early even if <head> does not, so we attach the style there and let it move
# with the cascade. Re-applied via add_style_tag after load as belt-and-braces.
_INIT_SCRIPT = (
    "(() => {"
    "const s = document.createElement('style');"
    "s.setAttribute('data-pipeline-render','1');"
    f"s.textContent = {DISABLE_MOTION_CSS!r};"
    "(document.head || document.documentElement).appendChild(s);"
    "})();"
)

# Resolves once fonts are ready and every <img> has settled (loaded or errored).
# page.evaluate awaits the returned promise.
_SETTLE_JS = (
    "() => Promise.all(["
    "document.fonts ? document.fonts.ready : Promise.resolve(),"
    "...Array.from(document.images).map(img =>"
    " img.complete ? Promise.resolve() :"
    " new Promise(res => {"
    "  img.addEventListener('load', res, {once:true});"
    "  img.addEventListener('error', res, {once:true});"
    " })"
    ")"
    "])"
)

# Extracts the rendered layout: one box per visible element, in document (CSS px,
# == PNG px since DSF==1) coordinates. This is the structure dimension's data source
# (grader) — captured here, on the single render path, so reference and agent boxes
# come from byte-identical conditions. We compare these boxes, never raw DOM tags.
EXTRACT_BOXES_JS = (
    "() => {"
    " const out = [];"
    " const all = document.body ? document.body.getElementsByTagName('*') : [];"
    " for (const el of all) {"
    "  const r = el.getBoundingClientRect();"
    "  if (r.width < 2 || r.height < 2) continue;"
    "  const s = getComputedStyle(el);"
    "  if (s.visibility === 'hidden' || s.display === 'none'"
    "     || parseFloat(s.opacity) === 0) continue;"
    "  out.push({tag: el.tagName.toLowerCase(),"
    "   x: r.x + window.scrollX, y: r.y + window.scrollY,"
    "   w: r.width, h: r.height,"
    "   text: (el.textContent || '').trim().length});"
    " }"
    " return out;"
    "}"
)

# Chromium flags chosen for determinism + headless-in-container survival.
#   --no-sandbox / --disable-dev-shm-usage : required when running as root in
#       the Ubuntu grading container (no user namespaces, small /dev/shm).
#   --hide-scrollbars                      : complements the CSS rule above.
#   --force-color-profile=srgb             : stable color, ignores monitor ICC.
#   --font-render-hinting=none / --disable-lcd-text : kill subpixel/hinting
#       variation so text rasterizes the same way every run on a given platform.
#   --disable-gpu                          : force the software path; avoids
#       GPU-driver-dependent rasterization differences.
LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--hide-scrollbars",
    "--force-color-profile=srgb",
    "--font-render-hinting=none",
    "--disable-lcd-text",
    "--disable-gpu",
    "--disable-skia-runtime-opts",
]


@dataclass(frozen=True)
class CaptureResult:
    """Outcome of capturing one page.

    Attributes
    ----------
    output_path : Path
        Where the PNG was written.
    width, height : int
        Pixel dimensions of the written PNG (== CSS px, since DSF == 1). The
        height is the page's full scroll height; the grader uses it directly.
    url : str
        The local http URL that was actually rendered.
    external_attempts : tuple[str, ...]
        Non-local request URLs the offline guard aborted while rendering this
        page. Non-empty means the site tried to reach the network — a
        determinism bug worth surfacing.
    """

    output_path: Path
    width: int
    height: int
    url: str
    external_attempts: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- #
# Local static server — serve the site so relative paths / links resolve like a
# real browser expects, instead of file:// (which breaks absolute-rooted paths
# and cross-page navigation).
# --------------------------------------------------------------------------- #


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D102 - silence per-request logging
        pass


class _StaticServer:
    """Threaded localhost static file server rooted at a directory.

    Usage::

        with _StaticServer(root) as srv:
            url = f"http://127.0.0.1:{srv.port}/home.html"
    """

    def __init__(self, root: Path | str):
        self.root = str(root)
        self.port: int | None = None
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_StaticServer":
        handler = partial(_QuietHandler, directory=self.root)
        # port 0 -> OS picks a free port; bind to loopback only.
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="render-static-server", daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


# --------------------------------------------------------------------------- #
# Browser context + offline guard
# --------------------------------------------------------------------------- #


def _new_context(browser):
    """Build the one canonical browser context. All render config lives here."""
    context = browser.new_context(
        viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        device_scale_factor=DEVICE_SCALE_FACTOR,
        locale=LOCALE,
        timezone_id=TIMEZONE_ID,
        color_scheme=COLOR_SCHEME,
        reduced_motion=REDUCED_MOTION,
    )
    context.add_init_script(_INIT_SCRIPT)
    return context


def _install_offline_guard(context) -> list[str]:
    """Abort any request to a non-local origin; return the list it records into.

    The same list object accumulates across every page rendered in this context;
    callers snapshot it per page.
    """
    attempts: list[str] = []

    def handler(route, request):
        url = request.url
        if url.startswith(("data:", "blob:", "about:")):
            route.continue_()
            return
        host = urlparse(url).hostname
        if host in ALLOWED_HOSTS:
            route.continue_()
        else:
            attempts.append(url)
            route.abort()

    context.route("**/*", handler)
    return attempts


def _png_size(path: Path) -> tuple[int, int]:
    """Read (width, height) from a PNG's IHDR — no Pillow dependency."""
    with open(path, "rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG file: {path}")
    width, height = struct.unpack(">II", head[16:24])
    return int(width), int(height)


def _capture_via_context(
    context, url: str, output_path: Path, attempts: list[str], extract_boxes: bool = False
) -> CaptureResult:
    """Core capture. Given a ready context + local http URL, write the PNG.

    This is the only place a screenshot is taken; capture_page and capture_site
    both funnel through here, guaranteeing identical treatment of both sides. When
    ``extract_boxes`` is set, also writes ``<output>.boxes.json`` (the structure
    dimension's input) captured in the same settled state as the screenshot.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    before = len(attempts)
    boxes = None
    page = context.new_page()
    page.set_default_timeout(SETTLE_TIMEOUT_MS)
    page.set_default_navigation_timeout(NAV_TIMEOUT_MS)
    try:
        page.goto(url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
        # Re-apply disable-motion CSS post-load (init script already applied it
        # early; this guarantees it survives any head rewrite).
        page.add_style_tag(content=DISABLE_MOTION_CSS)
        # Settle: fonts + images.
        page.evaluate(_SETTLE_JS)
        page.screenshot(
            path=str(output_path),
            full_page=True,
            animations="disabled",
            caret="hide",
            scale="device",
        )
        if extract_boxes:
            boxes = page.evaluate(EXTRACT_BOXES_JS)
    finally:
        page.close()

    if boxes is not None:
        output_path.with_suffix(".boxes.json").write_text(json.dumps(boxes))

    width, height = _png_size(output_path)
    new_attempts = tuple(attempts[before:])
    if new_attempts:
        log.warning(
            "render: %d external request(s) aborted while capturing %s: %s",
            len(new_attempts),
            url,
            ", ".join(new_attempts),
        )
    return CaptureResult(
        output_path=output_path,
        width=width,
        height=height,
        url=url,
        external_attempts=new_attempts,
    )


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def _resolve_local_file(target: str) -> Path:
    if target.startswith("file://"):
        return Path(unquote(urlparse(target).path))
    return Path(target).expanduser().resolve()


def capture_page(url_or_file, output_path, extract_boxes: bool = False) -> CaptureResult:
    """Render a single page to ``output_path`` and return a CaptureResult.

    ``url_or_file`` may be:
      * a local ``.html`` file path (or ``file://`` URL) — we serve its parent
        directory over a throwaway local HTTP server so its assets/links
        resolve, then capture it;
      * an ``http://127.0.0.1.../localhost`` URL already being served (e.g. a
        server you stood up yourself) — captured directly.

    ``extract_boxes`` additionally writes ``<output>.boxes.json`` for the grader's
    structure dimension. Spinning up a browser per call is fine for one-offs; use
    ``capture_site`` to amortize the browser across many pages.
    """
    target = str(url_or_file)

    if target.startswith(("http://", "https://")):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=LAUNCH_ARGS)
            try:
                context = _new_context(browser)
                attempts = _install_offline_guard(context)
                return _capture_via_context(
                    context, target, Path(output_path), attempts, extract_boxes
                )
            finally:
                browser.close()

    file_path = _resolve_local_file(target)
    if not file_path.is_file():
        raise FileNotFoundError(f"page not found: {file_path}")
    root = file_path.parent
    rel = file_path.name
    with _StaticServer(root) as server, sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=LAUNCH_ARGS)
        try:
            context = _new_context(browser)
            attempts = _install_offline_guard(context)
            url = f"http://127.0.0.1:{server.port}/{rel}"
            return _capture_via_context(
                context, url, Path(output_path), attempts, extract_boxes
            )
        finally:
            browser.close()


def _discover_pages(site_dir: Path, pages) -> list[tuple[str, str]]:
    """Return [(stem, filename), ...] to capture.

    Default: every top-level ``*.html`` in ``site_dir``, sorted for stable
    ordering. Explicit ``pages`` entries may be given as ``"home"`` or
    ``"home.html"``; ``.html`` is appended when missing.
    """
    if pages is None:
        filenames = sorted(p.name for p in site_dir.glob("*.html"))
    else:
        filenames = []
        for entry in pages:
            name = str(entry)
            filenames.append(name if name.endswith(".html") else f"{name}.html")
    return [(Path(f).stem, f) for f in filenames]


def capture_site(site_dir, output_dir, pages=None, extract_boxes: bool = False) -> dict[str, Path]:
    """Render every page of a static site to ``output_dir`` as ``<stem>.png``.

    One browser + one local server for the whole site, so all pages are captured
    under byte-identical conditions and inter-page links resolve.

    Returns ``{page_stem: png_path}`` (e.g. ``{"home": .../home.png}``).
    ``extract_boxes`` also writes ``<stem>.boxes.json`` per page (grader structure
    dimension). Pages that try to reach the network are logged (determinism bug).
    """
    site_dir = Path(site_dir).expanduser().resolve()
    if not site_dir.is_dir():
        raise NotADirectoryError(f"site_dir is not a directory: {site_dir}")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    page_files = _discover_pages(site_dir, pages)
    if not page_files:
        raise ValueError(f"no .html pages found in {site_dir}")

    results: dict[str, Path] = {}
    with _StaticServer(site_dir) as server, sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=LAUNCH_ARGS)
        try:
            context = _new_context(browser)
            attempts = _install_offline_guard(context)
            for stem, filename in page_files:
                url = f"http://127.0.0.1:{server.port}/{filename}"
                out = output_dir / f"{stem}.png"
                res = _capture_via_context(context, url, out, attempts, extract_boxes)
                results[stem] = res.output_path
        finally:
            browser.close()
    return results


# --------------------------------------------------------------------------- #
# Determinism self-check + tiny usage example
# --------------------------------------------------------------------------- #


def determinism_check(url_or_file) -> bool:
    """Capture the same page twice and report whether the PNGs are byte-identical.

    Same-machine pixel determinism is the acceptance bar for this module.
    """
    import hashlib
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        a = Path(td) / "a.png"
        b = Path(td) / "b.png"
        capture_page(url_or_file, a)
        capture_page(url_or_file, b)
        ha = hashlib.sha256(a.read_bytes()).hexdigest()
        hb = hashlib.sha256(b.read_bytes()).hexdigest()
        identical = ha == hb
        log.info(
            "determinism: %s  (%s)", "IDENTICAL" if identical else "DIFFER", ha[:12]
        )
        return identical


if __name__ == "__main__":
    # Example / smoke test:
    #   python -m pipeline.render <site_dir> [out_dir]
    # Renders every page of a site, then verifies same-page determinism.
    import sys

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )

    if len(sys.argv) < 2:
        print("usage: python -m pipeline.render <site_dir> [out_dir]")
        raise SystemExit(2)

    site = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("_render_out")

    shots = capture_site(site, out)
    for stem, path in shots.items():
        w, h = _png_size(path)
        print(f"  {stem:12s} -> {path}  ({w}x{h})")

    # Determinism check on the first discovered page.
    first = next(iter(shots))
    page_file = site / f"{first}.html"
    ok = determinism_check(page_file)
    print(
        f"\ndeterminism ({first}.html): {'PASS — pixel-identical' if ok else 'FAIL — pixels differ'}"
    )
    raise SystemExit(0 if ok else 1)
