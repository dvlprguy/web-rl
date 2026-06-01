"""Dimension 3 — layout / structure similarity (Tier 0 + Tier 1).

Operates on the rendered element boxes extracted at render time (see
``pipeline.render`` ``EXTRACT_BOXES_JS``) — NOT on raw DOM tags, so it's
implementation-agnostic: divs vs. semantic tags don't matter, only where things
land. This is the grader's primary anti-hack (the screenshot-embed attack renders
as ~1 giant element → near-zero structure → the multiplicative combine zeroes the
reward) and an interpretable "did the structure land in the right place" signal.

A box is a dict: {tag, x, y, w, h, text} where text is the element's text length.

Tier 0 — aggregate stats (element count, text mass, box-size distribution).
Tier 1 — spatial *edge-density* grid (a giant <img> fills every cell but has no
          internal edges, so edge density, not occupancy, is what defeats it).
We deliberately stop here: Tier 2 (element matching) and Tier 3 (DOM tree-edit)
are out for v0 (see grader_v0.md).
"""

from __future__ import annotations

import numpy as np

_GRID = 24  # Tier-1 grid resolution
_AREA_BINS = 12  # log-spaced bins for the box-size distribution


def _ratio(a: float, b: float) -> float:
    """Symmetric ratio in [0, 1]: 1 when equal, → 0 as they diverge."""
    hi = max(a, b)
    return float(min(a, b) / hi) if hi > 0 else 1.0


def _size_hist(boxes: list[dict]) -> np.ndarray:
    """Normalised log-area histogram of the boxes."""
    if not boxes:
        return np.zeros(_AREA_BINS)
    areas = np.array([max(1.0, b["w"] * b["h"]) for b in boxes])
    logs = np.log10(areas)
    h, _ = np.histogram(logs, bins=_AREA_BINS, range=(0.0, 7.0))
    total = h.sum()
    return h / total if total else h.astype(np.float64)


def _edge_map(boxes: list[dict], g: int = _GRID) -> np.ndarray:
    """g×g map of how many box *edges* pass through each cell (coords normalised
    by each page's own extent, so it compares relative arrangement)."""
    m = np.zeros((g, g), dtype=np.float64)
    if not boxes:
        return m
    pw = max((b["x"] + b["w"]) for b in boxes) or 1.0
    ph = max((b["y"] + b["h"]) for b in boxes) or 1.0

    def cell(v: float, n: float) -> int:
        return int(np.clip(int(v / n * g), 0, g - 1))

    for b in boxes:
        gx0, gx1 = cell(b["x"], pw), cell(b["x"] + b["w"], pw)
        gy0, gy1 = cell(b["y"], ph), cell(b["y"] + b["h"], ph)
        m[gy0, gx0 : gx1 + 1] += 1  # top edge
        m[gy1, gx0 : gx1 + 1] += 1  # bottom edge
        m[gy0 : gy1 + 1, gx0] += 1  # left edge
        m[gy0 : gy1 + 1, gx1] += 1  # right edge
    return m


def _map_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Histogram-intersection of two L1-normalised maps → [0, 1]."""
    sa, sb = a.sum(), b.sum()
    if sa == 0 and sb == 0:
        return 1.0
    if sa == 0 or sb == 0:
        return 0.0
    return float(np.minimum(a / sa, b / sb).sum())


def structure_score(ref_boxes: list[dict], cand_boxes: list[dict]) -> float:
    """Combined Tier-0 + Tier-1 structural similarity in [0, 1]."""
    n_ref, n_cand = len(ref_boxes), len(cand_boxes)

    # Tier 0
    count_sim = _ratio(n_ref, n_cand)
    text_ref = sum(b.get("text", 0) for b in ref_boxes)
    text_cand = sum(b.get("text", 0) for b in cand_boxes)
    text_sim = _ratio(text_ref, text_cand)
    size_sim = float(np.minimum(_size_hist(ref_boxes), _size_hist(cand_boxes)).sum())

    # Tier 1
    grid_sim = _map_similarity(_edge_map(ref_boxes), _edge_map(cand_boxes))

    # Weighted mean of the four sub-signals. Grid (relative arrangement) and count
    # (raw structural mass — the anti-hack) carry the most weight.
    parts = [
        (count_sim, 0.30),
        (text_sim, 0.15),
        (size_sim, 0.15),
        (grid_sim, 0.40),
    ]
    return float(sum(s * w for s, w in parts) / sum(w for _, w in parts))
