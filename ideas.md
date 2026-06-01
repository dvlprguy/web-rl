# Ideas

## I1 — *Grader*

**Idea:** The generator produces a real multi-page website as **HTML/CSS source**, which we
then render to screenshots with a headless browser (Playwright). The agent sees only the rendered
screenshots; we keep the source + reference render as ground truth. We do **not** use an image
generation model (DALL·E / Imagen style) to produce the target screenshots directly.

## I2 — *>=5 Pages*

The hard part of "≥5 pages" is **page identity**, not page count. The grader must know which agent
page maps to which reference page; without a fixed mapping it has to *match* pages by similarity —
noisy, and corrupts the reward.

**Fix — a deterministic filename manifest** flowing through every stage. The generator names its
pages (`home`, `about`, …); screenshots, the agent's required outputs, and grading all key off those
names. The filenames *are* the contract, so grading is a straight per-page comparison — no matching.

**Distinctness trap.** "5 pages" only means something if the layouts genuinely differ (landing,
grid, form, article, pricing). 5 near-clones test nothing and let the agent copy-paste page 1 for a
high score. So add a **generation-time validator**: regenerate any site whose pages are too
structurally similar (cheap pairwise DOM/screenshot check). Read it as "≥5 *distinct* screens
sharing one design system."

**Reward shape.** Reward = **mean of per-page fidelity** (each continuous in [0,1]); a missing page
scores 0 for its slot, so "nailed 3, botched 2" lands mid-range and partial progress is smooth.
Don't add a separate "file exists" term — a missing file is just 0 fidelity for that page.

**Defaults.** 5–7 pages sampled per site; canonical roles that generalize — `home`, `about/info`,
`listing` (grid), `detail`, `form` (contact); shared nav/footer across all pages to test
design-system consistency.

**Lock down:** (1) filename contract *(first — everything depends on it)*, (2) distinctness
validator, (3) mean-of-pages aggregation, (4) page-role set + count range.

## I3 — *Stock image library for the generator* (low priority, late-stage)

Instead of generating fresh images per site (D4), keep a **pre-built local image library** the
generator picks from — directories by category, with a separate **tags/manifest file** (path →
tags like `food`, `hero`, `portrait`, aspect ratio). The generator queries by tag and drops the
right asset in; assets are already bundled and deterministic. Saves per-site image-gen cost and
makes asset reuse/curation easy. Not high priority — D4's generate-and-bundle works fine first;
revisit only if image generation becomes a cost/latency bottleneck at scale.

## I4 - inline-SVG/CSS
A couple of notes worth flagging: I leaned on emoji for all "imagery" since external
images/fonts are off-limits — emoji glyphs render from the OS, so exact appearance varies
slightly by platform (macOS vs. Linux), which matters if these get screenshotted for grading. If
you'd prefer fully deterministic visuals, I can swap the emoji for inline-SVG/CSS
illustrations. Want me to do that?

## I5 — *Agent crops images from the screenshot*

Why provide assets or mask at all? The photo is **already in the screenshot** the agent is given —
so the agent can crop that region and use it directly. Faithful replication, not reward hacking:
the output genuinely looks like the target.

This undercuts D4's masking premise ("agent can't control photo content"). If the pixels are in the
screenshot, the agent *can* reproduce them, so image regions become a fair, achievable part of the
score — no need to provide assets or mask.

**Catch — compositing.** Clean rectangular crops work for isolated image cards, but real designs
composite photos with overlaid text, gradient overlays, rounded masks, and bleeding neighbors. A
rectangular crop grabs the *composite*: crop a text-over-hero, then render your own `<h1>` on top →
**double text**; off-by-a-few-pixels boxes grab slivers of neighbors. So image fidelity becomes
*achievable but imperfect* — which suits a continuous reward (partial credit, no cliff).

**Consequence:** we don't force or assume cropping. Generate the reference site with images, hand
the agent only the screenshots, grade the rendered result — the agent picks its own strategy (crop,
gray box, recreate) and the reward reflects how close the final pixels land. The screenshot becomes
the single source of truth; the agent + grading sides get much simpler (drop "provide assets +
mask"). Reference still needs images *somehow* on the generation side.

## I6 — *Generator variety: seeded combinatorial spec → two-stage LLM*

**Problem.** A single prompt ("food-delivery site, make it nice") produces the *same* site every
time: the model collapses to its prior — hero + 3 feature cards, centered sans nav, teal accent,
rounded corners. Under-specification means it defaults on every axis at once, and its default is
singular. **Temperature won't fix this** — it perturbs copy, not design language.

**Fix — move the randomness out of the model and into a structured spec it must build to.**

**~6 orthogonal axes** (2, like type×theme, isn't enough — sites still *look* alike):
`site_type` (food/SaaS/editorial/e-commerce/portfolio/real-estate/fitness/fintech/nonprofit/travel…),
`aesthetic` (brutalist/Swiss-minimal/corporate/playful/editorial-magazine/retro-Y2K/dark-techy/
luxury-serif), `palette`, `typography`, `layout system`, `density`. Sampled independently → huge
combinatorial space → samples look unrelated.

**Two-stage LLM (the key move — separate *decide* from *build*).** Asking one prompt to both choose
and execute lets it collapse to its prior; splitting breaks the attractor:
1. **Art director:** a *seeded* code runner picks axis values, an LLM expands them into a concrete
   **design brief** (brand, voice, exact hex palette, font stacks, component inventory, the 5–7
   pages + per-page sections). The brief pins specifics so the builder can't default.
2. **Builder:** an LLM builds the site *to that brief* (one-shot, per D2).
Randomness lives in the seeded spec (reproducible); craft lives in the model.

**Coherence guardrail.** Independent axis sampling risks franken-sites (brutalist + luxury-serif +
neon-pastel = mush). The art-director brief step is where the axes get reconciled into something
that hangs together — preferred over rigid curated presets (more diversity).

**Bonuses.** (a) The sampled spec is **metadata/labels** per site → the receipt for the "10 tasks
showcasing the distribution" deliverable (provable coverage). (b) Powers **cross-site distinctness**
(dataset-level I2): track combos, refuse near-duplicates. (c) For the final 10, **stratified-sample**
to cover the axes rather than i.i.d. (which risks 3 minimalist-SaaS by chance).
