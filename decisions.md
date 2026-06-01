# Design Decisions

## D1 — Generate website *source*, not website *images*

**Decision:** The generator produces a real multi-page website as **HTML/CSS source**, which we
then render to screenshots with a headless browser (Playwright). The agent sees only the rendered
screenshots; we keep the source + reference render as ground truth. We do **not** use an image
generation model (DALL·E / Imagen style) to produce the target screenshots directly.

**Why not an image generator?** Three fatal problems:

1. **The target may not be realizable.** Image models hallucinate impossible layouts and garbled
   text. You'd be asking the agent to replicate a design that no HTML/CSS can actually produce —
   and grading fidelity against an un-realizable target is noise by construction.
2. **You have no canonical reference render.** Your only ground truth is a fuzzy generated image.
   Pixel-comparing the agent's crisp browser render against an AI image is apples-to-oranges.
3. **No source, no structure, no multi-page consistency.** The spec demands ≥5 coherent pages
   (shared nav, consistent theme). An image model won't give you a consistent 5-page site or a
   navigable structure.

**What we do instead — and why it's strictly better:** generating the source means the target is
guaranteed buildable, we get a pixel-perfect deterministic reference render, crisp text, and
controllable variety (we steer the generator with specs/prompts). Crucially, it also gives the
grader a **second ground truth** — the reference DOM/source — to compare structurally against the
agent's output, not just pixels.

## D2 — Generate all pages at once, or one by one?

**Decision:** All at once, on both sides. The filename contract (see ideas I2) makes the agent's
output a flat set of named HTML files regardless, so this only affects the generator and the agent
prompt:

- **Generator:** one shot for the whole site. Shared nav/footer/theme live in a single context, so
  the design system stays coherent; page-by-page generation drifts.
- **Agent:** give it all screenshots together. Mirrors the real task and lets it establish shared
  CSS once, then specialize per page.

Worth a later experiment: per-page prompting may surface different failure modes — keep as a probe,
not the default.

## D3 — Full-page screenshots of scrollable sites

**Decision:** Render `full_page=True` at a **locked viewport width** (1280px desktop); height flows
with content but is **bounded** at generation (~1–3 viewports, no unbounded pages). Settle before
capture for determinism — `networkidle`, fonts/images loaded, animations disabled, fixed device
scale — and render the agent's HTML with the **byte-identical** config (render parity is
non-negotiable; any difference is pure reward noise).

**Height mismatch (the crux):** reference and agent renders differ in height, so they can't be
pixel-diffed directly. We **top-align and pad the shorter to the taller's height** (don't resize to
a common height — that squishes vertical proportions, which is itself a fidelity signal). The height
delta becomes an honest diff band at the bottom, penalizing both missing and bloated content. VLM
judge sees the full images; tile very tall pages into vertical slices so downscaling keeps detail.

**Rejected — fixing height at generation (single fixed canvas):** doesn't actually bind the agent's
height (its render is whatever its HTML produces), so we'd have to crop to viewport-only and discard
below-the-fold content. Worse, it removes vertical layout — section order, spacing rhythm, the fold
— which *is* design, sacrificing the human-likeness axis the spec judges. Bounding (not fixing)
height keeps sites realistic while killing the pathological 10,000px page.

## D4 — Images: real bundled assets, not colored blocks

**Decision:** Sites use **real, model-generated images bundled into the task as local files** and
**provided to the agent** — not CSS colored blocks (that was only a first-prompt shortcut). The
agent gets the same asset files, so replication is about *layout and styling* of image regions
(size, crop, position, `object-fit`, radius), never regenerating photo pixels it only saw in a
screenshot — which is what a human does when handed assets.

**Why images are fine:** "no scraping" bans copying *real websites*, not using images. Generating
content photos and committing them locally is allowed, deterministic (offline, no CDN), and far more
human-like — the judged axis.

**Grading:** image regions graded as design elements; **raw photo pixels masked out of the
pixel-similarity metric**, so the score reflects placement/sizing/styling, not uncontrollable photo
content.

**Rejected:** external image URLs (nondeterministic, network-dependent, scraping-adjacent).
Colored-block placeholders kept only as a cheap fallback for genuinely image-light site types.

**Tradeoff:** generating + bundling images adds pipeline cost and asset management, and providing
assets makes the task marginally easier — but that's correct: we grade design replication, not image
synthesis.

## D5 — In-container workspace layout: `target/` in, `site/` out

**Decision:** Inside the Harbor task container (`/app`), a fixed convention both the instruction
and the verifier depend on:

- **`./target/`** — the reference screenshots (`<stem>.png`), the agent's **only** input.
- **`./site/`** — where the agent writes its replica (`site/<stem>.html` + `site/style.css`).

The agent sees only `target/` (screenshots, never the reference source). The verifier renders
`site/*.html` and compares each to `target/<stem>.png` (+ reference boxes bundled under `tests/`,
out of the agent's view). Keeping input and output in separate dirs avoids the agent's files
colliding with targets and gives the verifier an unambiguous place to render from. The instruction
template (`pipeline/templates/instruction.md`) and the (still-to-build) packager both key off this.

*(Note: the broader factory-vs-Harbor architecture boundary — offline pipeline produces a Harbor
dataset; agent = Harbor's native `claude_code` adapter, not ours — is summarised in
[`docs/overview.md`](docs/overview.md), not yet written as its own decision.)*

## D6 — Drop the perceptual (image-embedding + SSIM) dimension; grade in render-tree space

**Decision:** Remove the perceptual dimension (DINOv2/SigLIP2 embedding cosine blended with SSIM)
from the grader. Grade design fidelity in **render-tree / DOM space** (elements, text, computed
styles) rather than **image space**.

**Why — empirically, on Modal (`modal_perceptual.py`):** we scored three real pairs.

| pair | what changed | global CLS cos | dense-patch cos | SSIM | blended perceptual |
|---|---|---|---|---|---|
| git vs git_bad | minor degradation | 0.9988 | 0.958 | 0.960 | 0.9915 |
| git2 vs git_bad2 | same, diff bg colour | 0.9989 | 0.960 | 0.958 | 0.9912 |
| git vs **git_black** | **all elements removed** | 0.447 | 0.463 | 0.768 | **0.7325** |

Two failures, one fatal:

1. **No meaningful zero (fatal).** A page with *every element stripped* should score ≈0. Image
   metrics floored at **0.73 / 0.46** — two same-sized images always share background, margins, and
   "is a page," so embeddings bottom out ~0.5 and SSIM ~0.7. "Empty" and "faithful" collapse into a
   narrow high band with no honest bottom. A continuous reward that can't represent *absence of
   content* is unusable for training.
2. **No dynamic range where it matters.** Global CLS put a *bad* replica at 0.9988 (distance-from-
   perfect 0.0012) — the plausible-replica band, exactly where the agent lives, was dead. Dense
   patch features helped (~35× more separation, and independently agreed with SSIM), but still
   floored at 0.46 on the blank — so the dense fix addressed range, not the missing zero.

**The reframe:** because we **generate the reference source** (D1), we own the reference DOM — a far
richer ground truth than pixels. Grade against *it*: element inventory (matched/missing/extra via
box IoU → precision/recall/F1, natural zero), visible **text** overlap (true zero when content is
gone), and **computed styles** (colour/font/size deltas on matched elements — a bg-colour change is
then one small bounded delta, not a whole-image shift). Pixels were the wrong space; the render tree
is the right one. Structure (boxes) stays the backbone; perceptual does not return.

**Status:** perceptual already removed from `DEFAULT_WEIGHTS` in `pipeline/grader.py`; the module is
kept on disk but unused. `modal_perceptual.py` retained as the evidence/repro.

## D7 — Don't adopt Design2Code's CLIP visual-similarity term as a grader dimension

**Decision:** We ported Design2Code's high-level CLIP metric faithfully (`pipeline/metrics/clip.py`,
mirroring `NoviScl/Design2Code/.../visual_score.py`) to evaluate it on its own terms — but we do
**not** add it to the grader. Same failure mode as the perceptual dimension (D6): too little dynamic
range where the agent actually lives.

**The faithful port:** OpenAI `clip` package (`clip.load("ViT-B/32")` + `encode_image`), Telea
text-inpainting of detected text boxes (`cv2.INPAINT_TELEA`), square-resize to the short side
(`Image.LANCZOS`), and **raw cosine** as the score (not the `(1+cos)/2` remap we first used — that
inflated/compressed it off their scale). Wired into `modal_perceptual.py` (needs the GPU + `clip`).

**Why it's out — empirically, on Modal (raw cosine, text-masked):**

| pair | what changed | CLIP (raw cos) |
|---|---|---|
| git vs git_bad | minor degradation | 0.9863 |
| git2 vs git_bad2 | same, diff bg colour | 0.9867 |
| git vs **git_black** | **all elements removed** | **0.6795** |

1. **No range in the plausible-replica band.** The two *different* bad replicas score 0.9863 vs
   0.9867 — CLIP can't tell them apart (Δ 0.0004), exactly the band the agent trains in. Only a
   grossly-broken page moves it (0.68), and even that has no honest zero. Identical to D6's global-CLS
   failure.
2. **Text-masking is a near no-op for CLIP** (Δ ≤ 0.0004 masked vs unmasked across all three pairs).
   At 224² a full page's text is an unreadable smear, so inpainting it barely perturbs the embedding.
   Masking still matters for the *block-text* matcher, just not here.

**Why this is inherent, not a tuning bug — and what Design2Code actually does:** CLIP runs at
**224×224** (ViT-B/32's fixed input); webpages are huge, so it's structurally a coarse "is this even
the same page" signal. Design2Code agrees implicitly — CLIP is only **1 of 5 metrics at 0.2 weight**.
The discrimination lives in the *other four* (size/text/position/color), which run on the
**`full_page=True` native-resolution** screenshot via OCR-free block detection with bboxes normalized
to [0,1]. Final score = `0.2·(size + text + position + color + clip)`. We faithfully reproduced the
least important fifth; the real signal is full-res block matching — which we deliberately did **not**
port (it's the render-tree/DOM space we already own via D1/D6, reached more directly there).

**Status:** `pipeline/metrics/clip.py` + the `modal_perceptual.py` CLIP wiring kept as evidence/repro;
CLIP is **not** in `DEFAULT_WEIGHTS`. Confirms D6 from a second, independent metric: image-space
similarity at fixed low resolution lacks the range a continuous training reward needs; grade in
render-tree space.

## D8 — Drop the VLM rubric-judge dimension

**Decision:** Remove `vlm` from the grader. The active grader is now `{color: 0.4, structure: 1.0,
text_color: 0.6}` — all deterministic and **fully offline** (no API key, no network at verify time).

**Why — empirically, on a real Opus-4.7 trial (`eval-seed-67__FpJsqdf`), per-page rubric breakdown
(`vlm_breakdown.py`, 2 identical runs each):** the judge scores five 0–4 axes (layout, color,
typography, spacing, content), averaged to one [0,1] number. Three failures:

1. **Incomplete — it silently omits an axis.** Raw output on every page was
   `{"layout":4,"typography":3,"spacing":3,"content":4}` — **no `color` key**, despite the prompt
   demanding it. And `vlm_score` divides by however many keys come back, so the denominator (and thus
   the meaning of the number) shifts call-to-call.
2. **No dynamic range.** Every returned axis sits at **3–4 out of 4** (`content` 4/4 on all 7 pages).
   A decent replica and a great one are indistinguishable — the same dead-band that killed perceptual
   (D6) and CLIP (D7).
3. **Noisy.** `typography` swings ±1 between two calls on the *same* images (stdev 0.48), `spacing` ±1
   on some pages — so the little signal it has is partly run-to-run noise. A noisy reward actively
   harms the model being trained.

**The through-line (D6 → D7 → D8):** every holistic *image-/judge-based* visual metric we tried fails
the same way — no honest zero and/or no resolution in the plausible-replica band. The signal lives in
**deterministic render-tree / OCR-block measurements** (structure boxes, palette histogram, matched-
block text colour), which have honest zeros and real range. Bonus: dropping VLM makes the verifier
offline again — no key plumbed into the container, no network, fully deterministic.

**Status:** `vlm` removed from `DEFAULT_WEIGHTS` and from every task's `tests/test.sh`; the
`"vlm" in active` dispatch in `grader.py` and `pipeline/metrics/vlm.py` stay on disk as opt-in.
`vlm_breakdown.py` retained as the evidence/repro. Verifier images drop `litellm` and add
`tesseract-ocr` + `scipy` for the `text_color` dimension.

## D9 — Validate the grader with a degradation ladder (trust gate before scaling)

**Decision:** Before scaling to ≥10 tasks, prove the grader is monotone — that a worse replica
*always* scores lower — by deliberately damaging the truth site in controlled steps and confirming
the reward falls accordingly. A grader that's right at the top (perfect=1.0) and on a typical attempt
(~0.81) can still be wrong *in between*, and "in between" is exactly where the training signal lives.
This is the gate; we do not scale until the curve is clean.

**Method (`make_ladder.py` + `ladder_grade.py`):** start from a truth site and emit rungs that drop a
controlled % of body elements. Removal is **nested** (each harder rung's removals strictly contain the
easier rung's — we keep peeling random leaf elements off one parse, snapshotting at each level), so the
underlying content curve is monotone *by construction*; any non-monotonicity in the reward would be the
grader's fault, not the input's. Suffix = % of elements RETAINED (90 = 10% dropped … 0 = empty body).

**Ladder 1 — content drop (eval-seed-67, weights {color 0.4, structure 1.0, text_color 0.6}):**

| rung (retain %) | reward | color | structure | text_color |
|---|---|---|---|---|
| 100 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| 90  | 0.9042 | 0.9773 | 0.8304 | 0.9900 |
| 80  | 0.8424 | 0.9599 | 0.7337 | 0.9725 |
| 60  | 0.7533 | 0.9325 | 0.6008 | 0.9545 |
| 50  | 0.6951 | 0.9148 | 0.5157 | 0.9542 |
| 25  | 0.5134 | 0.8967 | 0.3723 | 0.8095 |
| 10  | 0.0580 | 0.8648 | 0.2272 | 0.0000 |
| 5   | 0.0463 | 0.8574 | 0.1460 | 0.0000 |
| 0   | 0.0039 | 0.8546 | 0.0000 | 0.0000 |

**Findings:**

1. **PASS — strictly monotone, honest ceiling (1.0) and honest floor (0.004).** Exactly what a
   continuous training reward needs, and what perceptual (D6) / CLIP (D7) / VLM (D8) all failed.
2. **The multiplicative combine is validated on real data.** The empty page scores ~0 even though
   `color` alone still reads 0.85 — `structure`'s honest zero drags the product down, so no single
   channel can prop up a gutted page. This is the anti-hack backbone working as designed.
3. **The three dimensions behave very differently:**
   - **`structure` is the workhorse** — smooth, near-linear in content, honest zero. Carries the signal.
   - **`text_color` is a cliff, not a gradient** — flat ~0.95 from 100%→50%, then falls to 0 once OCR
     finds too few text blocks (25%→10%). Effectively an "is there still text at all" gate, with little
     resolution in the high band where agents actually live.
   - **`color` is nearly a constant** — moves only 1.00→0.85 across the *entire* ladder including the
     empty page. **No honest zero, almost no range.** At weight 0.4 it dilutes more than it discriminates.

**Caveat / why a second ladder is needed:** Ladder 1 only exercises ONE failure mode — content removal —
which `structure` dominates by construction. It cannot judge whether `color`/`text_color` earn their
weight, because their real job is catching what `structure` is blind to: a site with all the right boxes
but the WRONG palette/typography. That requires a ladder that **holds structure fixed and degrades colour**
(hue shifts, wrong backgrounds, wrong text colours). See D10.

**Status:** Ladder 1 done; grader passes monotonicity. `color` weight is under review pending Ladder 2.
Still to do: run the content ladder on 2–3 more sites to confirm the curve shape generalises before
locking weights.

## D10 — Ladder 2 (colour-shift): the grader is nearly blind to colour fidelity

**Decision / finding:** A second ladder (`make_color_ladder.py`) holds STRUCTURE fixed and rotates the
hue of every colour token by an increasing angle (0°→180°), isolating `color` + `text_color`. Result:
the grader is **monotone but has almost no dynamic range on colour** — a maximally-wrong palette barely
dents the reward. Colour fidelity is currently under-measured; this is the main known grader weakness.

**Ladder 2 — hue rotation (eval-seed-67, structure held fixed):**

| rung (fidelity %) | hue shift | reward | color | structure | text_color |
|---|---|---|---|---|---|
| 100 | 0°   | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| 90  | +18° | 0.9720 | 0.9323 | 0.9999 | 0.9534 |
| 60  | +72° | 0.9421 | 0.9058 | 0.9999 | 0.8761 |
| 50  | +90° | 0.9367 | 0.9007 | 0.9999 | 0.8628 |
| 25  | +135°| 0.9287 | 0.8952 | 0.9999 | 0.8423 |
| 10  | +162°| 0.9257 | 0.8968 | 0.9999 | 0.8321 |
| 0   | +180°| 0.9217 | 0.8947 | 0.9999 | 0.8216 |

**Findings:**

1. **The harness works** — `structure` holds at 0.9999 throughout (layout untouched), so all movement is
   colour. And it is monotone.
2. **But the range is tiny.** Every hue rotated a full 180° (complementary — maximally wrong) still scores
   **0.92**. `color` moves only 1.00→0.89, `text_color` 1.00→0.82, and nearly all of that is in the first
   18° step — from +60° to +180° the reward barely moves. The grader can't meaningfully tell a correct
   palette from a badly wrong one.
3. **Diagnosis — background/text dominance.** Both metrics are dominated by the page regions hue-rotation
   can't move: the near-white background (`#f2ede2`) and near-black text (`#0e1f1a`) are low-saturation,
   so their hue barely changes; only the minority saturated accents flip. The global histogram (`color`)
   and matched-block colours (`text_color`) therefore hardly budge.

**Open question (do not over-conclude yet):** hue rotation preserves *lightness*, and these pages are
lightness-dominated — so a hue flip may be a genuinely small perceptual change. Before declaring the
colour metric dead weight, run a **lightness/scheme corruption** (dark-mode inversion, or lerp the whole
palette toward a distinct target including lightness). If reward still floors ~0.92, the metric is weak;
if it drops hard, hue-only was just a gentle test.

**Likely fix if the metric is confirmed weak:** move colour grading from whole-page aggregates to
**per-element computed styles** — compare each matched element's `background-color`/`color` — which needs
the pending box-extractor enrichment (computed styles, not just geometry). That sidesteps background
dominance because every element's colour is weighted by match, not by pixel area.

**Status:** Ladder 2 (hue) done. Lightness/scheme variant pending (the disambiguator). `color`/`text_color`
weights and the per-element-colour redesign are blocked on that result. Artifacts: `make_color_ladder.py`,
rungs in `ladder/eval-seed-67-color-*`.

## D11 — Add region-level image-space signals (`block_color`, `block_ssim`, `edge_ssim`); refine D6/D7

**Decision:** Add three deterministic, pixel-based grader dimensions — per-matched-region colour
(`block_color`), within-block SSIM (`block_ssim`), and global edge-map SSIM (`edge_ssim`) — reusing the
existing LLEM OCR match pass. This **partially walks back D6/D7's "abandon image space" conclusion** — not
by re-adding the metrics those decisions killed (whole-image DINOv2/CLIP embeddings), but by adding the
*structural, full-resolution, per-region* image signals D6/D7 never actually tested.

**Why D6/D7 were right about what they measured but over-general in their conclusion:** D6/D7 evaluated
whole-image embeddings (DINOv2 global CLS, CLIP at 224²) *in isolation* and found no honest zero / no range
— true. But "image space is the wrong space, grade in render-tree space" generalised from the two *weakest*
representatives of image space (holistic, low-res, single-vector) to all of it. The counter-evidence: a
reference implementation grades **purely** in image space yet gets honest zeros *and* real range by working
(1) at full resolution, (2) per-matched-block rather than whole-image, and (3) as a *composition* of many
signals, most of which floor on a blank page. The honest-zero property is a property of the *composition*,
not of the space. So we keep the render-tree backbone (`structure`) but stop treating image space as poison.

**What we added (and why each):**
- `block_color` — per-matched-region mean-colour CIEDE2000, area-weighted. **The D10 fix.** The global
  histogram `color` dim is dominated by the page's near-white bg / near-black text, so a 180° hue flip still
  scored 0.92 (D10). Scoring colour per *matched region* removes whole-page background dominance — each
  region weighted by match, not by pixel area — which is exactly the per-element redesign D10 predicted.
  v1 = mean colour (reuses our scalar CIEDE2000); per-pixel ΔE is the documented v2 if range is short.
- `block_ssim` — area-weighted windowed SSIM over matched crops. Catches within-block render fidelity (font
  weight/family, fill, glyphs) that `block_match`/`position` are blind to: a matched line in the wrong font
  lands in the right place but looks different inside.
- `edge_ssim` — SSIM over Sobel edge maps of the **top-align-padded** (D3, not squished) full images.
  Block-independent; catches typography shape + illustration/component outlines globally, robust to flat
  fills. A lean Sobel stand-in for the Canny-edge SSIM in Design2Code-style graders.

**Lean by design (no new deps):** all three are numpy/scipy/pillow only — no skimage/cv2, consistent with
the D6/D8 stance (offline, deterministic, no torch/API; we already hand-rolled CIEDE2000 to avoid skimage).
SSIM is hand-rolled via `scipy.ndimage.uniform_filter`, edges via `scipy.ndimage.sobel`. The existing
verifier image runs them as-is — no Dockerfile change, no rebuild-for-deps.

**Evidence so far (smoke test on the `eval-quartz-99-hard` reference screenshots):**

| pair | block_match | text_color | block_color | block_ssim | edge_ssim |
|---|---|---|---|---|---|
| home vs home (perfect) | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| home vs about (diff page, same brand) | 0.152 | 0.848 | 0.955 | 0.316 | 0.682 |
| about vs products (diff page) | 0.316 | 0.835 | 0.956 | 0.285 | 0.693 |

- Honest ceiling holds — perfect = 1.0, and the full grader self-vs-self reward = 1.0 across all six dims.
- `block_ssim` and `edge_ssim` show **real range** on different content (0.29–0.32, 0.68–0.69).
- `block_color` ≈ 0.955 across *different pages* is **correct** (same brand → same palette), so this test
  cannot probe its range. The D10 fix is therefore **wired but unproven** — only the D10 colour/lightness
  ladder (same page vs a hue-/lightness-shifted copy) can confirm it.

**Caveats:**
1. **Provisional weights.** Added at `block_color` 0.6 / `block_ssim` 0.4 / `edge_ssim` 0.4 alongside the old
   set. These are honest mid-band signals (~0.4–0.7 on a decent page), so in the *geometric* mean they pull
   the absolute reward DOWN vs the old 3-dim set — the grader now seeing failures it was blind to, not a
   regression. Re-run the D9/D10 ladder before locking; global `color` becomes a drop candidate once
   `block_color` earns its range.
2. **Text-only blocks.** Our detector is OCR-text-only, so `block_ssim`/`block_color` cover text regions;
   pure illustration / section-fill fidelity is only caught globally by `edge_ssim`. Per-illustration block
   scoring needs a visual-block detector (which would change `block_match` semantics) — deferred to v2.

**Status:** Implemented (`pipeline/metrics/{imageutil,llem,edge}.py`; wired into `grader.py` DEFAULT_WEIGHTS;
`grade.py` + `build_task.sh` `test.sh` now share DEFAULT_WEIGHTS as one source of truth). Honest ceiling +
`block_ssim`/`edge_ssim` range verified. `block_color` range and final weights are **blocked on the D10
colour/lightness ladder re-run** (next). Existing tasks pick up the new dims on rebuild.

## D12 — Ladders 3 & 4: typography ladder + colour re-run/disentangle (closes D11's blocker, refines D10)

**Decision:** Extend the ladder suite from "damage everything / shift every hue" to **per-dimension isolation
ladders** — each corrupts ONE axis and holds the rest fixed, so every active dim is validated for three
things independently: monotone, real range, and isolation (off-axis dims stay flat). This resolves D11's
explicit blocker (`block_color` range + final weights) and refines D10.

Two new generators, mirroring `make_color_ladder.py`'s two-mode shape:
- `make_type_ladder.py` (`--mode weight|family`) — holds structure + colour fixed, mangles only the font.
  The ONLY ladder that exercises `block_ssim` / `edge_ssim` (D11 added them; only a smoke test existed).
- `make_color_ladder.py --target text|surface` — recolours ONLY the glyph `:root` vars vs ONLY the surface
  vars, to disentangle `text_color` (glyph colour) from `block_color` (region mean, bg-dominated).

**Implementation note (bug found + fixed):** the truth `style.css` ends with stray HTML junk
(`</style></body></html>` — a generation artifact). A CSS parser drops any rule that *follows* `</style>`, so
appending the type override at EOF silently did nothing (every rung scored 1.0). Fixed by inserting the
override *before* the junk. Lesson logged: model-generated CSS can carry trailing HTML; the type ladder
guards against it, and it's worth a generator-side strip.

**Result 1 — typography ladder (`block_ssim`/`edge_ssim` now validated on a controlled ladder):**

| rung | reward | block_color | block_ssim | edge_ssim | structure | text_color |
|---|---|---|---|---|---|---|
| 100 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| 90 | 0.8974 | 0.9701 | 0.5646 | 0.9109 | 0.9605 | 0.9712 |
| 60 | 0.8169 | 0.9588 | 0.3480 | 0.8487 | 0.9218 | 0.9296 |
| 50 | 0.7936 | 0.9309 | 0.2881 | 0.8485 | 0.9269 | 0.9086 |
| 0 | 0.7894 | 0.9557 | 0.2593 | 0.8513 | 0.9192 | 0.9303 |

(family mode; serif→sans→monospace + weight/letter-spacing ramp). `block_ssim` has **the widest range of any
dim** (1.0→0.26), `edge_ssim` moves clearly (1.0→0.85). Off-axis isolation holds: `block_color`/`text_color`
stay ~0.93–0.97, `structure` leaks only to ~0.92 (real text reflow from font swaps — measured, not hidden).
**Monotone through the meaningful range, then a ~0.01–0.02 noise floor at the saturated tail** (OCR jitter on
maximally-mangled text) plus one family-tier ordering bump (Arial vs Courier aren't cleanly ordered in
SSIM-distance). Wrong fonts cost ~20% of reward — a one-axis miss on a 5-dim geometric mean, which is the
right magnitude.

**Result 2 — colour re-run, all tokens (D11's `block_color` blocker, D10's open question):**

| corruption | block_color range | reward range | verdict |
|---|---|---|---|
| hue shift (lightness preserved) | 1.0 → 0.79 (0.21) | 1.0 → 0.92 | ~2× the old global `color` (0.10); still gentle |
| lightness inversion | 1.0 → 0.45 (0.55) | 1.0 → 0.42, strictly monotone | **D10 FIXED** |

`block_color` earns real range under the corruption that matters (scheme/lightness), confirming the D11 design
and the decision to drop global `color` (already commented out of `DEFAULT_WEIGHTS`). Hue-only stays gently
scored — arguably **correct**: a tint-rotated dark site at constant lightness *is* a closer replica than a
light-inverted one, so a small hue penalty is defensible, not a bug.

**Result 3 — disentangle (lightness, glyphs-only vs surfaces-only):**

| target recoloured | block_color | text_color | structure | reads as |
|---|---|---|---|---|
| SURFACE only | 1.0 → **0.32** (range 0.68) | 1.0 → 0.75 | **1.0000** (exact) | block_color = the surface signal |
| TEXT only | 1.0 → **0.96** (range 0.04, ~flat) | 1.0 → 0.79 | **1.0000** (exact) | block_color ⊥ glyph colour ✓ |

The two colour dims are **confirmed non-redundant**: recolouring only glyphs barely moves `block_color`
(range 0.04 — region mean is background-dominated), recolouring only surfaces moves it hard (0.68). Structure
is byte-exact 1.0 both ways (HTML untouched) — clean isolation.

**Caveats surfaced (all honest, on the fix list):**
1. **`text_color` is contrast-coupled.** Surface-only recolour still moved it to 0.75 — the glyph-colour
   *estimator* samples the minority-vs-background pixels, so inverting the background perturbs the estimate
   even when the glyph CSS colour is unchanged. It's an estimator artifact, not a true text-colour change.
2. **`text_color` breaks down when text ≈ background luminance** (invisible text): non-monotone wobble at the
   text-only tail, where near-black text on a dark bg gives the estimator nothing to sample. Edge case;
   undefined-by-construction rather than a grader regression.
3. **`block_ssim` is contrast-coupled** — collapses to ~0.01 under lightness inversion, not just under font
   changes. SSIM sees luminance, so it's a render-fidelity signal, not a pure typography signal. Acceptable
   (it *should* punish a contrast-wrecked render), but don't read it as "fonts only".

**Status:** D11 unblocked. `block_color` range proven; weights hold; global `color` stays dropped. Every
active dim now has at least one isolation ladder (structure→content ladder, block/text colour→colour ladders,
block_ssim/edge_ssim→type ladder). Remaining: the noise-floor tail and tier-ordering bump argue for a
tolerance-banded monotonicity check (the D-?? scorecard) rather than zero-tolerance arrows; generalise across
2–3 more sites.