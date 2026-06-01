# Grader metrics — explained

A living explainer for every metric in the live grader, plus an FAQ per metric
(questions asked while reviewing them). For the *decisions* behind the grader see
`decisions.md` (D6–D11); this doc is the "how each detector actually works".

## The active set

The grader scores each page on five metrics and combines them with a **weighted
geometric mean** (multiplicative — a near-zero in any one tanks the page, the
anti-hack backbone), then averages across pages (a missing page = 0).

| # | metric | weight | one-liner |
|---|---|---|---|
| 1 | `structure`   | 1.0 | *Where* things are laid out (DOM boxes). The backbone + anti-hack. |
| 2 | `block_color` | 0.6 | Colour of each matched text region (per-region, the D10 fix). |
| 3 | `text_color`  | 0.3 | Colour of the matched text glyphs themselves. |
| 4 | `block_ssim`  | 0.3 | *Within-block* render fidelity (font weight/family, fill). |
| 5 | `edge_ssim`   | 0.3 | Global typography / illustration **shape** (edge map). |

Weights are recalibrated-but-provisional (tuned on one site so far). `color`
(global histogram) was dropped after the D11 ladder work.

---

## 1. `structure` — weight 1.0 (the backbone)

**Measures:** *where things are laid out* — the page skeleton. Same number of
elements, same sizes, same spatial arrangement? Deliberately **blind to colour and
to what's inside each box**.

**Runs on:** the **rendered DOM boxes** (not pixels, not OCR). `pipeline/render.py`
dumps every visible element as `{tag, x, y, w, h, text}`; `structure` compares the
reference box list to the agent box list. This is the one metric using the DOM
ground truth we own (D1), which makes it implementation-agnostic (`<div>` vs
`<section>` doesn't matter — only where it lands).

**Tech / libs:** **no ML model** — deterministic/classical. Box extraction:
**Playwright + Chromium** (injected JS, `getBoundingClientRect`) at render time. The
metric math: **numpy only** (histograms, the 24×24 grid, histogram intersection). No
torch/sklearn/cv2/OCR. Fully offline and deterministic.

**Computed** (`pipeline/metrics/structure.py`) as a weighted mean of four sub-signals:
- **count (0.30):** ratio of element counts (`min/max`).
- **text-mass (0.15):** ratio of total text length across boxes.
- **size-histogram (0.15):** are box *sizes* distributed similarly (log-area
  histogram intersection)? Catches "right count, wrong sizes".
- **edge-grid (0.40):** a 24×24 grid of how many box **edges** pass through each
  cell (coords normalized per-page), compared by histogram intersection. The actual
  spatial-arrangement signal.

**Its two jobs:**
1. **Honest zero + anti-hack.** Blank page → ~0; one giant box (the "paste a
   screenshot-sized element" hack) → near-0 edge-grid. The multiplicative combine
   then tanks the whole reward — no other metric can rescue a structurally-broken
   page.
2. **Graceful content gradient.** Declines smoothly and monotonically as content is
   removed (ladder D9), so it carries the "how much did you build" signal.

**Catches:** layout, element count, spatial arrangement, gross size distribution.
**Blind to:** colour, fonts, box contents (that's metrics 2–5).
**Caveat:** boxes are geometry-only today (computed-style enrichment is queued); the
edge-grid sub-signal is load-bearing, the others guard degenerate cases.

### FAQ

**Q: Explain edge-grid more — and what happens if the agent site is just 2–3 pixels off?**

Edge-grid lays a **24×24 grid** over the page and, for each box, marks the cells its
**four edges** (top/bottom/left/right) pass through — so each box adds a hollow
rectangle *outline* into the grid, not a filled area. Summed over all boxes you get a
24×24 map of "how much box-boundary is in each cell"; do it for both sides, normalize
each to sum 1, and take the **histogram intersection** (Σ element-wise `min`) → [0,1].

Two choices matter: (a) **edges not fills** — a giant `<img>` fills every cell by
*area* but only its perimeter by *edges*, so edge-density defeats the one-big-box
hack; (b) **per-page normalized coords** — it compares *relative* arrangement, so a
uniformly-taller page still maps to the same cells.

**2–3 px offset → essentially nothing happens, by design.** On a 1280px-wide page each
cell is ~**53px wide** (1280 ÷ 24) and ~80px tall. A 2–3px shift is ~5% of a cell, so
an edge stays in the same cell → map unchanged → no penalty. The only way a tiny shift
moves anything is an edge sitting exactly on a cell boundary tipping across — 1–2 cells
out of 576, negligible. So `structure` has a built-in tolerance of roughly **half a
cell (~25px)** before small offsets register. That's intentional (don't punish render
jitter), and the opposite of raw pixel-SSIM (which *would* ding a 2–3px shift). The
trade-off: it also can't see *fine* misalignments (a 20px-off element reads as "fine")
— catching those is the job of the within-block/edge metrics, not this one.

---

## 2. `block_color` — weight 0.6 (the D10 colour fix)

**Measures:** did each region get the right **fill/surface colour** (the section
background a piece of text sits on)? The metric that finally gives the grader real
colour range, after D10 showed the global histogram was nearly colour-blind.

**Pipeline (3 stages, shared with metrics 3 & 4):**
1. **Detect text blocks (OCR).** Run **Tesseract** on each screenshot → words with
   bboxes; group words into lines by Tesseract's `(block, par, line)` numbering, union
   boxes → one `TextBlock` per line (normalized coords). One OCR pass per image, reused.
2. **Match reference ↔ agent blocks.** Build a **text-similarity** matrix
   (`difflib.SequenceMatcher` ratio) and solve the optimal 1-to-1 pairing with the
   **Hungarian algorithm** (`scipy.optimize.linear_sum_assignment`); drop pairs below
   0.5 similarity.
3. **Compare region colour.** Per matched pair: crop the region from both images, take
   the **mean RGB** of each, compute **CIEDE2000** (`ΔE00`) → `max(0, 1 − ΔE/100)`.
   Average over pairs, **area-weighted** by reference region size.

**Why it fixes D10:** the old `color` was one histogram over the *whole page*, so the
dominant near-white bg / near-black text drowned everything (a 180° hue flip barely
moved it). `block_color` scores **per matched region** and averages them equally, so
the page background can't dominate. On the lightness ladder it moved smoothly and
monotonically (1.0 → 0.45 on full dark-mode inversion).

**Tech / libs:** **Tesseract OCR** (the `tesseract` binary, via subprocess → TSV) —
the **only learned/ML model anywhere in the grader**. **scipy** `linear_sum_assignment`
(Hungarian) + **`difflib`** (stdlib) for matching. **CIEDE2000 + sRGB→Lab hand-rolled**
in `llem.py` (no skimage/colormath). numpy (crops/means) + PIL (load). Deterministic,
offline.

**Catches:** section/surface palette fidelity per region — what the global histogram missed.
**Blind to:** colour of **non-text** regions (illustrations, photo panels) since blocks
are text-only; and anything where OCR finds too few matches (the "OCR cliff" → 0, shared
with metrics 3 & 4).
**Caveat:** uses the region **mean** colour (v1) — collapses within-region variation;
per-pixel ΔE is the documented v2.

### FAQ

**Q: Why CIEDE2000 and not plain RGB distance?**
RGB distance doesn't match human perception — two greens far apart in RGB can look
identical, and some small RGB gaps look very different. CIEDE2000 is the standard
perceptual colour-difference formula, so the score tracks what a person would actually
call "wrong colour".

## 3. `text_color` — weight 0.3 (text *ink*, not surface)

Reuses the **same OCR-detect + Hungarian-match** front-end as `block_color`; the only
difference is **which colour it compares**. `block_color` = region *mean* colour (the
surface); `text_color` = the **glyph ink colour** (the letters themselves).

**Isolating ink from background** (`_estimate_text_color`): inside each block's bbox,
(1) the most common quantized colour = **background**; (2) **text pixels = the minority
that differ** from it (distance > 40); (3) take the **median** of those → the glyph
colour (fallback: the pixels furthest from bg if contrast is low). Estimated once at
detect-time, stored on the `TextBlock`. `text_color_score` then compares `ref.color` vs
`cand.color` per matched pair via **CIEDE2000**, **plain mean** over matches (*not*
area-weighted, unlike `block_color`).

**Complementary to `block_color`:** "is the *surface* the right colour?" vs "is the
*text* the right colour?" A site with right backgrounds but wrong heading accent scores
high on `block_color`, low here.

**Tech / libs:** **Tesseract OCR** (shared detect) + **scipy** Hungarian + **`difflib`**
(shared matching). Glyph estimation: **pure numpy** (quantize, `np.unique` mode,
distance threshold, `np.median`) — no model. **CIEDE2000 hand-rolled**. Deterministic,
offline.

**Catches:** text ink-colour fidelity (wrong accent, gray-instead-of-black body).
**Blind to:** non-text colour; quality depends on the glyph-estimation heuristic, which
can misfire on **low-contrast / busy-background text**. Plain mean → a tiny mislabeled
line counts as much as a big headline.
**Why weight 0.3:** correlated with `block_color` (shares the OCR pass + OCR cliff →
both crater together), so the ladder recalibration downweighted it to avoid double-
counting in the geometric mean. Lightness ladder: 1.0 → 0.69 (has range, gentler than
`block_color`).

## 4. `block_ssim` — weight 0.3 (within-block *texture*)

Same matched pairs as #2/#3, but compares the **actual rendered pixels inside each
region** — "does this matched line *look* the same inside?" Catches **wrong font
weight/family, wrong size, missing inline glyphs** — things in the right place (so
`structure` is happy) and the right colour (so the colour metrics are happy) but
rendered differently.

**How:** per matched pair, crop the region from both images, convert to **grayscale**,
resize the agent crop to the ref crop's shape, compute **SSIM**. Average over pairs,
**area-weighted**; crops < 7px (the SSIM window) are skipped.

**What SSIM is:** Structural Similarity Index (Wang et al., 2004). Slides a small window
over both images and, per window, compares local **luminance**, **contrast**, and
**structure** (pixel co-variance); averages to [0,1] (1 = identical). Not a pixel diff —
it measures local texture patterns, i.e. "rendered the same way".

**Tech / libs:** **Tesseract OCR** (shared detect) + **scipy** Hungarian + **`difflib`**
(shared matching). Grayscale: numpy (Rec601 luma); crop resize: **PIL**. **SSIM
hand-rolled** in `imageutil.py` via **`scipy.ndimage.uniform_filter`** (standard windowed
formula, *no skimage*, no learned model). Deterministic, offline.

**Catches:** font weight/family, glyph rendering, text size, fill texture, missing inline
icons inside text regions.
**Blind to:** non-text regions; shares the **OCR cliff** (→0 at low content).
**Key caveat:** **grayscale SSIM conflates colour with texture** — inverting luminance
anti-correlates pixels, so it cratered to ~0.01 on the lightness ladder, partly
double-counting the colour metrics (a reason it's downweighted). Its **unique** value
(right layout + right palette + *wrong font/illustration*) is exactly what the current
ladders can't isolate → a fixed-palette font/illustration ladder is needed before its
0.3 weight is more than a guess. (Also the source of the one tiny non-mono blip on the
hue ladder — luminance noise on recolours.)

## 5. `edge_ssim` — weight 0.3 (global *shape*, colour-invariant)

The odd one out — **no OCR, no matching, no blocks**. Works on the whole page: *"do the
two pages have the same shapes/outlines?"* — glyph shapes, component borders,
illustration outlines. The only metric that sees **non-text shape** (icons, SVGs),
because it doesn't depend on detecting text.

**How** (`edge.py`): (1) **top-align-pad** both full images to a common canvas (D3 —
pad the shorter with white, don't squish, so a height mismatch shows as a blank low-edge
band); (2) **grayscale**; (3) build an **edge map** via **Sobel gradient magnitude**
(high where brightness changes fast = edges; ~0 in flat fills), normalized to [0,255];
(4) **SSIM** between the two edge maps.

**Why edges, not raw pixels:** whole-page grayscale SSIM is dominated by big flat
backgrounds; taking edges first discards the flats and keeps only structure (glyph +
component outlines). And since edges live where *contrast* is — which a recolour
preserves — it's **colour-invariant** (stayed ~0.996 through any palette change on the
ladder). Isolating shape from colour is its unique property; no other metric does it.

**Tech / libs:** **no OCR, no matching, no ML model.** `top_align_pad` + `to_gray`
(numpy), **Sobel** via **`scipy.ndimage.sobel`** + numpy `hypot`, **SSIM** hand-rolled
via **`scipy.ndimage.uniform_filter`**. PIL for load. Deterministic, offline. (Sobel is a
lean stand-in for a Canny-edge SSIM — same intent, no hysteresis thresholds.)

**Catches:** typography shape, component/illustration **outlines** globally — including
the non-text shapes the OCR trio misses.
**Two caveats:**
1. **No honest zero** — a blank page scores ~**0.90** (two mostly-zero edge maps look
   "similar"; the D6 failure mode). **Safe only because of the multiplicative combine** —
   `structure`/`block_color` hit 0 on a blank and the geometric mean floors the page. It
   must never be a standalone reward or carry dominant weight.
2. **Low content-range** (1.0 → ~0.88, fairly flat). Colour-invariance is proven;
   shape-discrimination at fixed layout (its real job) is what the current ladders can't
   isolate — the illustration ladder is the gap.

---

## How the five fit together

`structure` says *where*; the two colour metrics say *what colour* (surface vs ink);
`block_ssim` says *what the text looks like inside*; `edge_ssim` says *what shape
everything is*.

| design axis | covered by |
|---|---|
| **Layout** (where things are) | `structure` (backbone) · `edge_ssim` (loosely) |
| **Colour — surface** | `block_color` |
| **Colour — text ink** | `text_color` |
| **Typography / font render** | `block_ssim` (texture) · `edge_ssim` (glyph shape) |
| **Illustrations / icons / non-text shape** | `edge_ssim` *only* (and weakly) |

**Combine:** weighted geometric mean (any one near-zero tanks the page — anti-hack);
`structure` is the only metric with an honest zero; per-site = mean over pages, missing
page = 0.

**Two facts to remember:**
- **`block_color`, `text_color`, `block_ssim` share one Tesseract+Hungarian front-end** —
  correlated, all hit the same "OCR cliff" at low content. Main correlation risk in the
  combine; why two are downweighted.
- **Biggest coverage gap = non-text fidelity** (illustrations, SVGs, icons): only
  `edge_ssim`, weakly and unproven. That + typography-at-fixed-palette is what the
  proposed fixed-palette font/illustration ladder would test.
