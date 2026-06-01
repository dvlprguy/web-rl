"""Two-stage website generator for the RL replication recipe.

WHY TWO STAGES (see ideas.md / I6)
----------------------------------
A single "make a nice food-delivery site" prompt produces the *same* site every
time — the model collapses to its prior (hero + 3 cards, centered sans nav, teal
accent). Temperature only perturbs copy, not design language. So we move the
randomness OUT of the model and into a structured spec it must build to:

    seed ──> [sampler]  pick orthogonal axis values (deterministic)
                  │     site_type, aesthetic, palette, typography, layout
                  │     (density is set per task by `difficulty`, not sampled)
                  ▼
            [stage A · art director]  axes ──LLM──> concrete design brief
                  │     brand, voice, exact hex palette, fonts, per-page sections
                  ▼
            [stage B · builder]       brief ──LLM──> the multi-page site (HTML/CSS)

The seed makes the *spec* reproducible (same theme as the rest of the pipeline);
the LLM still supplies the craft. Splitting "decide" from "build" is the point:
asking one prompt to do both lets it default; pinning the specifics in a brief
first breaks the attractor and gives genuinely varied sites.

The sampled spec + brief are written alongside the site as ``spec.json`` /
``brief.json`` — these are the metadata "receipt" that lets us prove the dataset
spans the distribution (the "10 tasks showcasing variety" deliverable).

NOTE ON DETERMINISM
-------------------
Only the *sampler* is deterministic. The two LLM calls are not (and shouldn't be
— we want creativity), so two runs of the same seed yield the same brief axes but
different rendered pixels. The spec is the provenance, not a byte-for-byte hash.

USAGE
-----
    export ANTHROPIC_API_KEY=...                 # never hardcoded
    python -m pipeline.generate out/site-01 --seed tuvoki-42 --difficulty hard
    # writes out/site-01/{home.html,...,style.css, spec.json, brief.json}

    from pipeline.generate import sample_spec, generate_site
    spec = sample_spec("tuvoki-42", "hard")      # deterministic, no API
    result = generate_site("out/site-01", seed="tuvoki-42", difficulty="hard")
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger("pipeline.generate")

# --------------------------------------------------------------------------- #
# The axes (I6). Sampled independently → large combinatorial space. Keep each
# list human-curated and visually distinct; the art-director reconciles a sampled
# combination into a coherent brief, so we don't need the axes to be mutually
# compatible — just individually meaningful.
# --------------------------------------------------------------------------- #

SITE_TYPES = [
    "food delivery / restaurant",
    "SaaS product / developer tool",
    "online store / e-commerce",
    "news / editorial magazine",
    "personal portfolio / studio",
    "real estate / property listings",
    "fitness / gym / wellness",
    "fintech / banking",
    "nonprofit / charity",
    "travel / hospitality booking",
    "education / online course",
    "music / artist / event",
]

AESTHETICS = [
    "brutalist — raw, heavy borders, system fonts, stark",
    "Swiss / international minimalism — grid-driven, lots of whitespace",
    "corporate clean — safe, trustworthy, soft shadows",
    "playful — rounded, bright, friendly, illustrative",
    "editorial magazine — strong typographic hierarchy, serif headlines",
    "retro / Y2K — gradients, chrome, early-web nostalgia",
    "dark techy — near-black, neon accents, monospace touches",
    "luxury / elegant — generous spacing, refined serif, muted",
]

PALETTES = [
    "monochrome (black/white/grey, one tiny accent)",
    "high-contrast complementary pair",
    "soft pastels",
    "earthy / natural tones",
    "neon on dark",
    "muted corporate blues & greys",
    "warm sunset (corals, ambers)",
    "cool jewel tones (deep teal, plum, emerald)",
]

TYPOGRAPHY = [
    "serif display headlines + sans body",
    "all geometric sans (e.g. system Helvetica/Arial stack)",
    "humanist sans with a monospace accent",
    "big oversized display type",
    "condensed/compressed headlines",
    "classic serif throughout",
]

LAYOUTS = [
    "centered single column",
    "left sidebar navigation",
    "asymmetric / broken grid",
    "full-bleed edge-to-edge sections",
    "bento-box card grid",
    "split-screen halves",
]

# Information density, set explicitly per task (NOT sampled) by `difficulty`.
# Difficulty IS density here, so the worded description is what steers the model:
# it needs concrete, evocative anchors (a real site archetype) rather than a bare
# adjective — LLMs under-deliver on "very dense" but reach for "like a government
# portal". The "designed, not messy" clause in `hard` is load-bearing: without it,
# "very dense" collapses into cluttered output that fails on design quality. Both
# the `difficulty` label and this resolved text are recorded in spec.json.
DENSITY_BY_DIFFICULTY: dict[str, str] = {
    "easy": (
        "Sparse and breathable. Few elements per screen, one clear focal point per "
        "section, generous whitespace, a short page. Think a startup landing page or "
        "a personal portfolio — every section says one thing and gives it room."
    ),
    "medium": (
        "Moderately dense. Several elements per section and repeating component "
        "patterns — card grids, feeds, lists — with a persistent nav (and maybe a "
        "sidebar) and a few screens of scrolling. Think a blog, a store listing, or a "
        "social feed: busy but rhythmic, the same building blocks reused down the page."
    ),
    "hard": (
        "Very dense and information-rich. Many distinct elements packed into every "
        "screen — multi-column layouts, data tables, dense navigation, forms, "
        "callouts, long link-heavy footers — lots competing for attention. Think a "
        "government portal, a news front page, or an enterprise dashboard. It must "
        "read as densely designed, not messy: a real design system carrying a heavy "
        "information load, with a consistent grid, spacing, and palette holding all "
        "that density together."
    ),
}
DIFFICULTIES: tuple[str, ...] = tuple(DENSITY_BY_DIFFICULTY)  # easy, medium, hard
DEFAULT_DIFFICULTY = "medium"

# Page roles. "home" is always present and first; the rest are sampled to a
# 5–7 page count. Stems are stable identifiers (the I2 filename contract); the
# art-director maps each to type-appropriate content, so generic role names are
# fine across site types.
HOME_ROLE = "home"
OTHER_ROLES = [
    "about",
    "products",  # listing / grid
    "detail",  # single item / article / profile
    "contact",  # a form
    "pricing",
    "gallery",
    "blog",
    "services",
    "team",
    "faq",
]


@dataclass(frozen=True)
class SiteSpec:
    """The design spec for one site: the I6 axes sampled from `seed`, plus
    `difficulty` — an explicit per-task input (not sampled) that resolves to the
    `density` description fed to the art director."""

    seed: str
    difficulty: str  # "easy" | "medium" | "hard" — set per task, drives `density`
    site_type: str
    aesthetic: str
    palette: str
    typography: str
    layout: str
    density: str  # resolved from `difficulty` via DENSITY_BY_DIFFICULTY
    pages: list[str]  # page stems, home first (the I2 filename contract)


def sample_spec(seed: str, difficulty: str = DEFAULT_DIFFICULTY) -> SiteSpec:
    """Build one SiteSpec: axes sampled deterministically from `seed`, density set
    explicitly by `difficulty` ("easy" | "medium" | "hard"). No API call."""
    if difficulty not in DENSITY_BY_DIFFICULTY:
        raise ValueError(
            f"unknown difficulty {difficulty!r}; expected one of {DIFFICULTIES}"
        )
    rng = random.Random(seed)
    n_pages = rng.randint(5, 7)
    others = rng.sample(OTHER_ROLES, n_pages - 1)
    return SiteSpec(
        seed=seed,
        difficulty=difficulty,
        site_type=rng.choice(SITE_TYPES),
        aesthetic=rng.choice(AESTHETICS),
        palette=rng.choice(PALETTES),
        typography=rng.choice(TYPOGRAPHY),
        layout=rng.choice(LAYOUTS),
        density=DENSITY_BY_DIFFICULTY[difficulty],
        pages=[HOME_ROLE, *others],
    )


# --------------------------------------------------------------------------- #
# Prompts. Kept here as editable constants (they ARE the recipe — tune freely).
# --------------------------------------------------------------------------- #

# Stage A — the art director. Turns sampled axes into a concrete, coherent brief.
# We demand strict JSON so stage B has structured inputs, and we explicitly ask
# it to RECONCILE the axes (the coherence guardrail from I6) rather than stapling
# them together. Palette is emitted as exact hex so the builder can't drift.
ART_DIRECTOR_SYSTEM = """You are an expert art director and brand designer. Given a \
set of sampled design constraints, you invent a single, coherent, *distinctive* \
website concept and express it as a precise design brief.

Rules:
- Honour every sampled axis, but RECONCILE them into something that hangs together \
as one real brand — resolve any tension tastefully rather than stapling styles on \
top of each other.
- Be specific and opinionated. Avoid generic defaults (no reflexive "hero + three \
feature cards" unless the concept genuinely calls for it).
- The site renders fully OFFLINE: choose font stacks from web-safe / system fonts \
only (no Google Fonts or web downloads). Imagery must be describable as CSS/inline \
SVG or simple shapes — assume no external image files.
- Output STRICT JSON only (no prose, no markdown fences). Exactly this schema:

{
  "brand": "string",
  "tagline": "string",
  "voice": "1-2 sentences on tone/personality",
  "palette": {
    "bg": "#hex", "surface": "#hex", "text": "#hex", "muted": "#hex",
    "primary": "#hex", "secondary": "#hex", "accent": "#hex"
  },
  "fonts": { "heading": "css font-family stack", "body": "css font-family stack" },
  "signature_details": ["concrete distinctive design choices, 3-6 items"],
  "imagery": "how visuals are handled with CSS/SVG (no external files)",
  "pages": [
    { "stem": "home", "title": "string", "purpose": "string",
      "sections": ["ordered list of the concrete sections on this page"] }
  ]
}

The "pages" array MUST contain exactly the stems given to you, in order, each with a \
distinct layout/purpose so no two pages look like clones."""

ART_DIRECTOR_USER = """Design a website concept from these sampled constraints:

- Site type:    {site_type}
- Aesthetic:    {aesthetic}
- Palette mood: {palette}
- Typography:   {typography}
- Layout system:{layout}
- Density:      {density}

Pages (use exactly these stems, in this order): {pages}

Return the design brief as strict JSON."""

# Stage B — the builder. Builds the site to the brief. We hand it the brief as
# JSON and demand the files back in a delimiter format (robust to quote/escape
# issues that plague JSON-wrapped HTML). All the hard constraints we've settled
# (offline, 1280px, bounded height, filename contract, shared chrome) live here.
BUILDER_SYSTEM = """You are a meticulous front-end engineer. You implement a design \
brief as a complete, static, multi-page website using only HTML and CSS.

Hard constraints:
- Static HTML + CSS only. No JavaScript. No animations or transitions.
- Renders FULLY OFFLINE: no external URLs, CDNs, web fonts, or image files. Use the \
font stacks from the brief, and create all imagery with CSS and/or inline SVG.
- One shared stylesheet, style.css, linked by every page. A consistent header nav \
and footer on every page (links use the exact page filenames).
- Design for a 1280px-wide desktop viewport. Keep each page roughly 1-3 screens tall.
- Implement the brief faithfully: its palette (exact hex), fonts, voice, signature \
details, and each page's sections. Make every page a genuinely different layout — \
do not reuse one template across pages.
- Write real, brand-appropriate copy (no lorem ipsum).

OUTPUT FORMAT — return every file, each introduced by a line of exactly this form \
and nothing else on that line:

===FILE: home.html===
<full file contents>
===FILE: style.css===
<full file contents>

Emit one ===FILE: <name>=== block per page (named <stem>.html for every stem in the \
brief) plus style.css. No commentary before, between, or after the blocks."""

BUILDER_USER = """Build the complete website for this brief. Produce exactly these \
files: {files}.

Design brief (JSON):
{brief}

Return all files in the ===FILE: <name>=== format. No other text."""


# --------------------------------------------------------------------------- #
# LLM plumbing (litellm; model + key from env)
# --------------------------------------------------------------------------- #

DEFAULT_MODEL = os.environ.get("GENERATOR_MODEL", "anthropic/claude-opus-4-8")


def _complete(
    system: str,
    user: str,
    *,
    temperature: float | None = None,
    max_tokens: int,
    continue_on_truncation: bool = False,
    max_rounds: int = 6,
) -> str:
    """One chat completion via litellm. Reads ANTHROPIC_API_KEY from the env.

    A single `max_tokens` is never enough for a worst-case multi-page site, and
    hitting the cap mid-file silently truncates the last page into broken HTML.
    So when ``continue_on_truncation`` is set (Stage B), we detect a "length"
    finish and ask the model to continue from exactly where it stopped, stitching
    the pieces — handling sites larger than any single response window.

    Without that flag (Stage A's JSON brief, where a mid-continuation stitch could
    corrupt the JSON), a truncated response raises instead of being silently used.
    """
    import litellm

    litellm.suppress_debug_info = True
    if "ANTHROPIC_API_KEY" not in os.environ and "anthropic" in DEFAULT_MODEL:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Export it (keep keys out of code/git)."
        )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    # Some newer models (e.g. claude-opus-4-8) reject `temperature` outright, so
    # only send it when explicitly set.
    extra = {"temperature": temperature} if temperature is not None else {}
    chunks: list[str] = []
    for round_i in range(max_rounds):
        resp = litellm.completion(
            model=DEFAULT_MODEL,
            max_tokens=max_tokens,
            messages=messages,
            **extra,
        )
        choice = resp.choices[0]
        text = choice.message.content or ""
        chunks.append(text)
        truncated = choice.finish_reason == "length"
        if not truncated:
            break
        if not continue_on_truncation:
            raise ValueError(
                "model output hit the token cap and was truncated "
                f"(finish_reason=length, max_tokens={max_tokens}). "
                "Raise max_tokens for this call."
            )
        log.info("output truncated; requesting continuation (round %d)", round_i + 2)
        messages.append({"role": "assistant", "content": text})
        messages.append(
            {
                "role": "user",
                "content": "Continue from exactly where you stopped. Do not repeat "
                "anything you already wrote; output only the remaining content.",
            }
        )
    else:
        log.warning(
            "hit max continuation rounds (%d); output may be incomplete", max_rounds
        )
    return "".join(chunks)


def _strip_json(text: str) -> str:
    """Tolerate accidental ```json fences around an otherwise-strict JSON body."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n", "", t)
        t = re.sub(r"\n```$", "", t.strip())
    return t.strip()


_FILE_BLOCK = re.compile(r"^===FILE:\s*(.+?)\s*===\s*$", re.MULTILINE)


def _parse_files(text: str) -> dict[str, str]:
    """Split builder output on ===FILE: name=== markers into {filename: content}."""
    parts = _FILE_BLOCK.split(text)
    # parts = [preamble, name1, body1, name2, body2, ...]
    files: dict[str, str] = {}
    for i in range(1, len(parts), 2):
        name = parts[i].strip()
        body = parts[i + 1].strip("\n") if i + 1 < len(parts) else ""
        files[name] = body
    return files


# --------------------------------------------------------------------------- #
# Stage A / Stage B
# --------------------------------------------------------------------------- #


def art_direct(spec: SiteSpec) -> dict:
    """Stage A: expand sampled axes into a concrete design brief (dict)."""
    user = ART_DIRECTOR_USER.format(
        site_type=spec.site_type,
        aesthetic=spec.aesthetic,
        palette=spec.palette,
        typography=spec.typography,
        layout=spec.layout,
        density=spec.density,
        pages=", ".join(spec.pages),
    )
    raw = _complete(ART_DIRECTOR_SYSTEM, user, max_tokens=8000)
    try:
        brief = json.loads(_strip_json(raw))
    except json.JSONDecodeError as e:
        raise ValueError(f"art director did not return valid JSON: {e}\n{raw[:500]}")
    return brief


def build_site(brief: dict, spec: SiteSpec) -> dict[str, str]:
    """Stage B: build the site files from the brief. Returns {filename: content}."""
    files_expected = [f"{stem}.html" for stem in spec.pages] + ["style.css"]
    user = BUILDER_USER.format(
        files=", ".join(files_expected),
        brief=json.dumps(brief, indent=2),
    )
    raw = _complete(
        BUILDER_SYSTEM,
        user,
        max_tokens=16000,
        continue_on_truncation=True,
    )
    files = _parse_files(raw)
    if not files:
        raise ValueError(f"builder returned no parseable files:\n{raw[:500]}")
    return files


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class GenerateResult:
    site_dir: Path
    spec: SiteSpec
    brief: dict
    files: list[str]
    missing_pages: list[str]  # expected stems whose .html was not produced


def generate_site(
    out_dir, seed: str, difficulty: str = DEFAULT_DIFFICULTY
) -> GenerateResult:
    """Run the full pipeline for one site and write it (plus metadata) to out_dir.

    `difficulty` ("easy" | "medium" | "hard") sets the information-density tier.
    Writes: <stem>.html for each page, style.css, plus spec.json and brief.json
    (the distribution "receipt"). Logs a warning for any expected page the builder
    failed to emit (the I2 distinctness/filename contract is checked downstream).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    spec = sample_spec(seed, difficulty)
    log.info("spec[%s · %s]: %s · %s", seed, spec.difficulty, spec.site_type, spec.aesthetic)

    brief = art_direct(spec)
    files = build_site(brief, spec)

    for name, content in files.items():
        (out_dir / name).write_text(content, encoding="utf-8")

    (out_dir / "spec.json").write_text(json.dumps(asdict(spec), indent=2))
    (out_dir / "brief.json").write_text(json.dumps(brief, indent=2))

    produced = set(files)
    missing = [s for s in spec.pages if f"{s}.html" not in produced]
    if missing:
        log.warning("builder missing pages: %s", ", ".join(missing))

    return GenerateResult(
        site_dir=out_dir,
        spec=spec,
        brief=brief,
        files=sorted(files),
        missing_pages=missing,
    )


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    ap = argparse.ArgumentParser(description="Generate one website (two-stage LLM).")
    ap.add_argument("out_dir", help="output directory for the generated site")
    ap.add_argument("--seed", required=True, help="seed string (drives the axes)")
    ap.add_argument(
        "--difficulty",
        default=DEFAULT_DIFFICULTY,
        choices=DIFFICULTIES,
        help="information-density tier — sets the density axis (default: %(default)s)",
    )
    ap.add_argument(
        "--spec-only",
        action="store_true",
        help="just print the sampled spec (no API calls)",
    )
    args = ap.parse_args()

    if args.spec_only:
        print(json.dumps(asdict(sample_spec(args.seed, args.difficulty)), indent=2))
        raise SystemExit(0)

    res = generate_site(args.out_dir, seed=args.seed, difficulty=args.difficulty)
    print(f"\n  wrote {len(res.files)} files to {res.site_dir}")
    print(f"  difficulty: {res.spec.difficulty}")
    print(f"  type:      {res.spec.site_type}")
    print(f"  aesthetic: {res.spec.aesthetic}")
    print(f"  pages:     {', '.join(res.spec.pages)}")
    if res.missing_pages:
        print(f"  WARNING missing pages: {', '.join(res.missing_pages)}")
