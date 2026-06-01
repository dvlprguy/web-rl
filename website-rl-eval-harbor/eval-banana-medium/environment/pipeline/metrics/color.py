"""Dimension 2 — colour / palette similarity (deterministic).

Compares the colour *distribution* of the two renders via histogram intersection.
Cheap, stable, shift-invariant — captures "did they get the colours right", which
is a big chunk of perceived design fidelity. Layout-blind on its own (right colours
+ wrong layout still scores high here), which is why colour is only one dimension
of the multiplicative combine.
"""

from __future__ import annotations

import numpy as np

from pipeline.metrics import imageutil

# Downscale before histogramming: colour distribution is scale-insensitive, and a
# few hundred px per side is plenty while keeping it fast.
_MAX_SIDE = 256


def _hist(rgb: np.ndarray, bins: int) -> np.ndarray:
    """Normalised flat 3-D RGB histogram (sums to 1)."""
    q = (rgb.astype(np.int32) * bins // 256).clip(0, bins - 1)  # per-channel bin idx
    flat = q[..., 0] * bins * bins + q[..., 1] * bins + q[..., 2]
    h = np.bincount(flat.ravel(), minlength=bins**3).astype(np.float64)
    total = h.sum()
    return h / total if total else h


def color_score(ref_rgb: np.ndarray, cand_rgb: np.ndarray, bins: int = 8) -> float:
    """Histogram-intersection colour similarity in [0, 1] (1 = identical palette)."""
    ref = imageutil.downscale(ref_rgb, _MAX_SIDE)
    cand = imageutil.downscale(cand_rgb, _MAX_SIDE)
    h1, h2 = _hist(ref, bins), _hist(cand, bins)
    # Intersection of two L1-normalised histograms is already in [0, 1].
    return float(np.minimum(h1, h2).sum())
