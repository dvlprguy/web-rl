# `pipeline/render.py` — the deterministic screenshot module

The **single rendering path** for the whole recipe. Every screenshot the
pipeline produces — the reference render of a generated site **and** the render
of the coding agent's reconstructed output — goes through this one module, so
the two sides are always captured under byte-identical conditions. That render
parity is the #1 requirement (see `decisions.md` / **D3**): any divergence
between how we capture reference vs. agent is pure noise in the grader's reward.

There is intentionally **no second code path** and no per-call override of the
render config. To change how pages render, change a module-level constant in
`render.py`.

## API

```python
from pipeline.render import capture_page, capture_site, CaptureResult

# One page (local file, file:// URL, or an already-served http://127.0.0.1 URL).
res = capture_page("site/home.html", "out/home.png")
print(res.output_path, res.width, res.height, res.external_attempts)

# A whole site: one browser + one local server for all pages.
# Defaults to discovering every top-level *.html in the directory.
shots = capture_site("site/", "out/")          # -> {"home": Path(".../home.png"), ...}
shots = capture_site("site/", "out/", pages=["home", "about", "menu"])  # explicit subset
```

`capture_site` returns `dict[str, Path]` keyed by page **stem** (the filename
without `.html`) — this is the filename contract from `ideas.md` / **I2**, so
grading is a straight per-page comparison with no fuzzy matching.

## What makes a capture deterministic

Fixed for **every** capture (reference and agent alike):

- `full_page=True`, locked viewport **width 1280**, `device_scale_factor 1`
  (1 device px = 1 CSS px, so PNG dims equal CSS px and compare across machines).
- Site served over a **local static HTTP server** rooted at the site dir — never
  `file://` — so relative assets and inter-page links resolve like a real browser.
- **Settle before capture:** `networkidle` → `document.fonts.ready` → every
  `<img>` `complete`.
- **All animation/transition disabled** via injected CSS (applied early through
  an init script *and* re-applied after load) plus `prefers-reduced-motion: reduce`
  and Playwright's `animations="disabled"` at screenshot time.
- **Scrollbar hidden** (CSS + `--hide-scrollbars`) so it can't perturb layout width.
- **Locale + timezone pinned** (`en-US`, `UTC`).
- **Offline guard:** a route handler **aborts any request to a non-local origin**
  and records it (`CaptureResult.external_attempts`, plus a logged warning). A
  site reaching the network is a determinism bug we want surfaced — it also
  enforces the no-external-resources rule.

This module does **no** padding / aligning / resizing / masking — it only emits
the raw, faithful full-page PNG. Normalizing the two renders for comparison is
the grader's job (D3).

### Determinism scope

Re-rendering the *same* HTML on the *same* machine is **pixel-identical** (the
acceptance bar). `capture_page` launches a fresh browser process per call, so the
built-in check below proves determinism even *across processes*:

```bash
python -m pipeline.render <site_dir> [out_dir]
# renders every page, then re-captures one page twice and asserts the PNGs
# are byte-identical (exit code 0 = PASS).
```

Cross-*platform* renders (macOS vs. Linux) are **not** guaranteed byte-identical
because text rasterization differs by OS. That's fine: the grader always renders
**both** reference and agent on the **same** platform (the Ubuntu grading
container), so only same-machine determinism matters — and that we guarantee.

## Setup

```bash
# macOS (dev) and Linux:
pip install playwright
playwright install chromium
```

**Ubuntu grading container.** Use `--with-deps` so Chromium's shared libraries
are installed, and note the module already passes `--no-sandbox` /
`--disable-dev-shm-usage` (required when running as root with a small
`/dev/shm`):

```dockerfile
RUN pip install playwright && playwright install --with-deps chromium
```

No further container tweaks are needed — `LAUNCH_ARGS` in `render.py` handles the
headless-root-container gotchas.
