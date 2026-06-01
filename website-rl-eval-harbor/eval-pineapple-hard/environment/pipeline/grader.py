"""The grader — agent render → continuous reward vs. the reference design.

This is the Harbor verifier's brain (see grader_v0.md and decisions D3/D5, idea I2).
It runs per page across the active dimensions, combines them MULTIPLICATIVELY (so no
single dimension can be sacrificed — the anti-hack backbone), then averages across
pages with a missing page scoring 0.

    per page:   { color, structure, text_color, ... } → weighted geometric mean
    per site:   mean over the REFERENCE pages (missing candidate page = 0)      [I2]

Active set + weights = DEFAULT_WEIGHTS below (color, structure, text_color — fully
offline, deterministic). Also implemented but OFF by default / opt-in only:
perceptual (embeddings+SSIM, D6), vlm (rubric judge, D8), and the other Design2Code
LLEM dims (block_match / position / text, via pipeline.metrics.llem).

Inputs are two directories of rendered artifacts, one PNG + one boxes sidecar per
page stem (produced by pipeline.render with extract_boxes=True):
    <dir>/<stem>.png  and  <dir>/<stem>.boxes.json

Why geometric mean, not a weighted sum: a sum lets the agent max the easy channels
and ignore a hard one. A product means a near-zero in ANY dimension tanks the score
— e.g. the screenshot-embed hack scores ~1 on pixels/embeddings but ~0 on structure,
and the product kills it. A small floor keeps the reward continuous (no hard zeros)
while still penalising hard.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("pipeline.grader")

# Which dimensions are active, and their weights in the geometric mean. The layout
# signal comes from Design2Code's LLEM metrics (`block_match` + `position`), computed
# by OCR on the screenshots (pipeline.metrics.llem) rather than `structure` (rendered
# DOM boxes) — the boxes are low-confidence, and in Design2Code's Table 2 Position
# (+0.76) and Block-Match (+0.74) are the strongest human-aligned signals.
#
# `text` (LLEM) is implemented but OFF by default: Table 2 finds text *content*
# similarity NEGATIVELY correlated with human preference (-0.35), so it's a
# diagnostic, not a reward channel. Add it back only to study a site, never to train.
DEFAULT_WEIGHTS: dict[str, float] = {
    # "color": 0.4,  # global palette histogram (metrics.color) — weak range (D10)
    "structure": 1.0,  # DOM-box backbone — honest zero, anti-hack
    "text_color": 0.3,  # LLEM: matched-block text-GLYPH colour (CIEDE2000)
    # Region-level signals added to fix two known blindspots (Design2Code-v2 style):
    #   block_color — per-matched-REGION colour: the D10 colour-range fix. Once it
    #                 earns its range on the ladder, global `color` is a drop
    #                 candidate (block_color supersedes whole-page histograms).
    #   block_ssim  — within-block render fidelity (font weight/family, fill, glyphs).
    #   edge_ssim   — global typography / illustration shape (Sobel-edge SSIM).
    # PROVISIONAL weights — RE-RUN the D9/D10 ladder before locking. These are honest
    # mid-band signals (~0.4-0.7 on a decent page), so in the geometric mean they pull
    # the absolute reward DOWN vs the old 3-dim set — that's the grader now seeing
    # failures it was previously blind to, not a regression. The ladder recalibrates.
    "block_color": 0.6,
    "block_ssim": 0.3,
    "edge_ssim": 0.3,
}
# VLM rubric judge dropped (D8): incomplete (silently omits the color axis), no
# dynamic range (every axis pinned at 3–4/4), and ±1 noise on identical inputs.
# `pipeline/metrics/vlm.py` + the `"vlm" in active` dispatch below stay as opt-in.

# Alternatives to bake-off on the degradation ladder:
# DEFAULT_WEIGHTS = {"perceptual": 1.0, "color": 0.6, "structure": 1.0, "vlm": 0.6}
# Add "text": 0.x to any of these only as a diagnostic (see note above).


# Floor on each dimension before the log, so one near-zero channel pulls the reward
# down hard without collapsing it discontinuously to 0.
SCORE_FLOOR = 1e-3


@dataclass
class GraderConfig:
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    floor: float = SCORE_FLOOR


@dataclass(frozen=True)
class PageArtifacts:
    """One page's rendered artifacts for one side (reference or candidate)."""

    png: Path
    boxes: list[dict]

    @classmethod
    def load(cls, directory, stem: str) -> "PageArtifacts | None":
        png = Path(directory) / f"{stem}.png"
        if not png.is_file():
            return None
        boxes_path = Path(directory) / f"{stem}.boxes.json"
        boxes = json.loads(boxes_path.read_text()) if boxes_path.is_file() else []
        return cls(png=png, boxes=boxes)


# --------------------------------------------------------------------------- #
# Per-page scoring
# --------------------------------------------------------------------------- #


def _dimension_scores(
    ref: PageArtifacts, cand: PageArtifacts, active: set[str]
) -> dict[str, float]:
    """Run each active dimension. Heavy deps imported lazily, inside the branches."""
    from pipeline.metrics import imageutil

    scores: dict[str, float] = {}

    # Load pixels once if any full-image pixel dimension is active.
    if {"perceptual", "color", "edge_ssim"} & active:
        ref_rgb = imageutil.load_rgb(ref.png)
        cand_rgb = imageutil.load_rgb(cand.png)
        if "perceptual" in active:
            from pipeline.metrics import perceptual

            scores["perceptual"] = perceptual.perceptual_score(ref_rgb, cand_rgb)
        if "color" in active:
            from pipeline.metrics import color

            scores["color"] = color.color_score(ref_rgb, cand_rgb)
        if "edge_ssim" in active:
            from pipeline.metrics import edge

            scores["edge_ssim"] = edge.edge_ssim_score(ref_rgb, cand_rgb)

    if "structure" in active:
        from pipeline.metrics import structure

        scores["structure"] = structure.structure_score(ref.boxes, cand.boxes)

    # Block-Match / Text / Position / Text-Colour (Design2Code LLEM) share one OCR +
    # matching pass, so compute every active LLEM dimension in a single call.
    from pipeline.metrics.llem import LLEM_DIMENSIONS

    llem_active = LLEM_DIMENSIONS & active
    if llem_active:
        from pipeline.metrics import llem

        scores.update(llem.llem_scores(ref.png, cand.png, dims=llem_active))

    if "vlm" in active:
        from pipeline.metrics import vlm

        scores["vlm"] = vlm.vlm_score(ref.png, cand.png)

    return scores


def _combine(scores: dict[str, float], cfg: GraderConfig) -> float:
    """Weighted geometric mean of the dimension scores (with floor) → [0, 1]."""
    num = 0.0
    den = 0.0
    for dim, s in scores.items():
        w = cfg.weights.get(dim, 1.0)
        num += w * math.log(max(s, cfg.floor))
        den += w
    return math.exp(num / den) if den else 0.0


def grade_page(ref: PageArtifacts, cand: PageArtifacts, cfg: GraderConfig) -> dict:
    """Score one page across active dimensions and combine. Returns details."""
    active = set(cfg.weights)
    dims = _dimension_scores(ref, cand, active)
    combined = _combine(dims, cfg)
    return {"combined": combined, "dimensions": dims}


# --------------------------------------------------------------------------- #
# Per-site aggregation (I2)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class GradeResult:
    reward: float
    pages: dict[
        str, dict
    ]  # stem -> {combined, dimensions} | {combined: 0, missing: True}


def grade_site(
    reference_dir, candidate_dir, pages=None, cfg: GraderConfig | None = None
) -> GradeResult:
    """Grade a candidate site against the reference. Reward = mean over reference
    pages; a page the candidate didn't produce scores 0 for its slot (I2)."""
    cfg = cfg or GraderConfig()
    reference_dir = Path(reference_dir)

    if pages is None:
        pages = sorted(p.stem for p in reference_dir.glob("*.png"))
    if not pages:
        raise ValueError(f"no reference pages found in {reference_dir}")

    per_page: dict[str, dict] = {}
    for stem in pages:
        ref = PageArtifacts.load(reference_dir, stem)
        if ref is None:
            log.warning("reference page missing, skipping: %s", stem)
            continue
        cand = PageArtifacts.load(candidate_dir, stem)
        if cand is None:
            per_page[stem] = {"combined": 0.0, "missing": True}  # I2: missing = 0
            continue
        per_page[stem] = grade_page(ref, cand, cfg)

    if not per_page:
        raise ValueError("no gradable pages")
    reward = sum(p["combined"] for p in per_page.values()) / len(per_page)
    return GradeResult(reward=reward, pages=per_page)


def write_reward(result: GradeResult, logs_dir="/logs/verifier") -> None:
    """Write the Harbor reward: the scalar to reward.txt, plus a detailed report."""
    logs_dir = Path(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "reward.txt").write_text(f"{result.reward:.6f}\n")
    (logs_dir / "grade_report.json").write_text(
        json.dumps({"reward": result.reward, "pages": result.pages}, indent=2)
    )


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    ap = argparse.ArgumentParser(description="Grade a candidate site vs. a reference.")
    ap.add_argument(
        "reference_dir", help="dir of reference <stem>.png + <stem>.boxes.json"
    )
    ap.add_argument(
        "candidate_dir", help="dir of candidate <stem>.png + <stem>.boxes.json"
    )
    ap.add_argument(
        "--logs-dir", default="/logs/verifier", help="where to write reward.txt"
    )
    ap.add_argument(
        "--no-write", action="store_true", help="print only, don't write reward"
    )
    args = ap.parse_args()

    res = grade_site(args.reference_dir, args.candidate_dir)
    for stem, p in sorted(res.pages.items()):
        dims = p.get("dimensions", {})
        detail = " ".join(f"{k}={v:.3f}" for k, v in dims.items()) or "MISSING"
        print(f"  {stem:12s} {p['combined']:.3f}   {detail}")
    print(f"\n  REWARD = {res.reward:.4f}")
    if not args.no_write:
        write_reward(res, args.logs_dir)
