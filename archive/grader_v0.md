# Grader v0 — design

The grader converts the agent's rendered output back into a **continuous** reward vs. the
reference design. It is the heart of the trial: the model trains on this signal, so every
choice is made to avoid the two ways a grader fails.

## The two failure modes we design against

1. **Noise** — a high-variance reward trains the model on garbage. (The spec's explicit warning.)
2. **Reward hacking** — any cheap channel that can be maxed *without* real fidelity will be found.

Almost every single-metric grader fails one of these. Pixel-diff is stable but non-perceptual and
hackable; a raw VLM score is perceptual but noisy and hackable. So v0 is a **designed blend** —
and *how* we combine matters more than which metrics we list.

## Architecture at a glance

```
per page:
   reference render  ┐
   agent render      ┼─> 4 orthogonal dimensions, each in [0,1]
   reference DOM     ┘     1. perceptual  2. color  3. layout/structure  4. holistic(VLM)
                            │
                            ├─ combine ACROSS dimensions: geometric mean / soft-min  (anti-hack)
                            ▼
                     per-page score in [0,1]
across pages: mean (missing page = 0)   →   reward            [I2]
```

Two levels of combination, deliberately different:
- **within a dimension** → weighted sum (smooth, lets sub-signals complement).
- **across dimensions** → multiplicative (geometric mean / soft-min), so a near-zero in *any*
  dimension tanks the score. You cannot trade a hard dimension for an easy one — this is the
  anti-hacking backbone.

## The four dimensions

### 1. Perceptual similarity — vision embeddings + SSIM  *(core: from grader.md)*
Encode both screenshots with a **single, selectable** vision backend and take cosine similarity,
normalized to `[0,1]`. The backend is a config knob (`EMBEDDING_MODEL`), **not** an ensemble — exactly
one model runs per grading pass:

- **`dinov2`** — DINOv2 ViT-L/14, fed the *full rectangular* page (aspect-preserving, long-side
  capped, dims ×14). Structural/SSL features.
- **`siglip2-naflex`** — SigLIP2-NaFlex, native variable aspect via a patch budget.

Both still downscale (no model reads 2700px natively) — we keep resolution **high** (Modal GPU
affords it; D3's height bound keeps pages tractable) so text *appearance* survives, and aspect is
preserved either way. The **degradation ladder picks the default** backend; at grade time only the
selected one runs.

```
s_embed = (1 + cos(f_target, f_agent)) / 2
```

- Range `[0,1]`, smooth, robust to small pixel shifts, captures *semantic* "is this the same
  screen" — exactly where SSIM is brittle.

Blend with SSIM for precise layout, normalized `s_ssim = (SSIM + 1) / 2`:

```
perceptual = 0.8 · s_embed + 0.2 · s_ssim
```

Embeddings pull the agent toward the right screen; SSIM rewards matching the exact visual layout.

**Optional sharpening (steepness knob).** A steeper reward landscape can help RL distinguish
near-matches from far ones:

```
s = exp( -‖f_t - f_s‖² / τ )
```

`τ` trades exploration steepness against continuity — too small and the reward becomes effectively
discrete (violating the continuous requirement), too large and it's flat. **A tunable knob, not a
fixed choice** — we set it empirically on the validation ladder (below).

### 2. Color / palette — deterministic
Dominant-palette / histogram distance between the two renders. Cheap, stable, shift-invariant,
captures a big chunk of perceived fidelity ("did they get the colors right"). Layout-blind on its
own — which is why it's only one dimension.

### 3. Layout / structure — rendered element boxes  *(Tier 0 + Tier 1)*
Compare the **rendered element bounding boxes** (from the browser's layout — not raw tag names).
Shift-tolerant and implementation-agnostic: divs vs. semantic tags don't matter, only where things
land. This is also our **primary anti-hack** and the interpretable "did the structure land in the
right place" signal.

**Extraction — basically free.** Both sides already render through `pipeline/render.py`; while each
page is open, one `page.evaluate()` walks visible elements and grabs `getBoundingClientRect()`
(+ tag, text length), dumped as a JSON sidecar next to the PNG. We extract from the reference
*render* and the agent *render* identically — so we need no reference *source* and do no DOM
parsing. Symmetric and cheap.

**Comparison — Tier 0 + Tier 1 (no element matching).**
- **Tier 0 — aggregate stats:** element count, total text mass, box-size distribution. Trivial.
- **Tier 1 — spatial density map:** rasterize boxes into a coarse grid (~24×24), score per-cell
  **box-boundary/edge density** (not raw occupancy), compare via IoU/correlation. One function, no
  matching problem.

**Why this is the anti-hack.** The screenshot-embed attack renders as *one* `<img>` covering the
page; the real reference has hundreds of elements. Tier 0 element count (~1 vs. hundreds) → ~0, and
the multiplicative combine zeroes the whole reward. Tier 1 uses *edge density per cell* precisely
because a giant `<img>` fills every cell but has zero internal structure. We deliberately skip
**Tier 2** (element matching + IoU — medium, fiddly, noisy) and **Tier 3** (DOM tree-edit — hard
*and* wrong: it penalizes equivalent implementations) for v0; reach for Tier 2 only if the ladder
shows we need finer layout discrimination.

### 4. Holistic / typography — constrained VLM rubric
The VLM (Claude vision) judges what metrics miss (typographic feel, design intent). To keep it from
re-injecting noise: **never a raw 0–100.** Score concrete sub-dimensions against a rubric on a small
ordinal scale (0–4: layout, color, typography, spacing, content-completeness), anchored by "how
close is the candidate to *this* reference," then average. Ordinal rubric scoring is far more stable
than fine continuous numbers, and the reference is a perfect anchor. **Kept lighter-weight than the
deterministic backbone** so stability dominates.

## Anti-hacking (why multiplicative + structure)

- **Embed the reference screenshot as a background image** → near-perfect pixels *and* embedding,
  but a page that's one big `<img>` has trivial structure → dimension 3 reads ~0. Multiplicative
  combination kills the reward. (Note: embeddings, like pixels, are fooled by this — structure is
  the defense, which is why dimension 3 is non-negotiable.)
- **Copy one page to all pages** → each page graded vs. its *own distinct* reference (I2
  distinctness), so duplicates score low on the pages they don't match.
- **Blank page / right background color only** → color may score okay, but layout + perceptual ~0 →
  product ~0.

## Per-page aggregation
Every dimension runs per page; per-page scores averaged across pages; a **missing page scores 0**
for its slot (I2). No separate "file exists" term.

## Render normalization & where it runs
Both renders go through the single shared path (`pipeline/render.py`), then **top-aligned and
padded to max height** before pixel/SSIM comparison (D3 — never resize/squish; height delta is real
signal). The grader runs **in-container as the Harbor verifier** (`tests/test.sh`), reads the
agent's output from the workdir + bundled reference assets, and writes the aggregate to
`/logs/verifier/reward.txt` (with per-page / per-dimension sub-scores to `rewards.json` for the
report). (D5)

## Validation — the degradation ladder (how we *prove* monotonicity)
A grader is only trustworthy if it provably ranks worse replications lower. We build a ladder of
programmatically-degraded versions of a reference and require the grader to order them:

- shift palette → drop a section → swap font → jitter spacing → scramble layout → gray wireframe →
  blank page.

Plus fixed anchors:
- **reference-as-solution** → ~1.0 (ceiling; this is `solution/solve.sh`)
- **blank / random page** → ~0 (floor)
- **hack attempts** (screenshot-embed, single-color, copy-one-page) → must score low

This ladder is both the validation harness and a deliverable artifact, and it's how we tune the
weights and `τ`.

## Open decisions / knobs (to settle empirically on the ladder)
- **Embedding model:** selectable backend (`dinov2` ViT-L/14 vs. `siglip2-naflex`), default chosen
  by the ladder. One per run, never combined. (Takes the torch/weights dependency in the container.)
- **τ** and whether to apply exp-sharpening per-channel or to the final reward.
- **Weights:** within-perceptual (0.8/0.2 start) and the across-dimension combine (pure geometric
  mean vs. weighted, with small per-channel floors so a legitimately low-variance site isn't zeroed).
- **VLM weight:** co-equal dimension vs. lighter sanity layer (current lean: lighter).
- **Structural channel:** Tier 0+1 fixed for v0; whether to add Tier 2 (element matching) later
  depends on whether the ladder needs finer layout discrimination.
