"""Dimension — global edge / typography-shape similarity (deterministic).

SSIM over Sobel edge maps of the two full renders. Edge maps emphasise glyph
outlines and component borders and fall to ~0 on flat fills, so this catches
typography (font family/weight) and illustration / component-shape differences
that the box-layout dims (which only score WHERE blocks land) are blind to — and
that full-image pixel SSIM washes out under large flat backgrounds. This is the
block-independent counterpart to ``llem.block_ssim``.

The two renders differ in height; we top-align-pad to a common canvas (D3) rather
than resize, so a height/content mismatch shows up honestly as a low-edge band
instead of being squished away. Pillow/numpy/scipy only — no skimage/cv2, no API.
"""

from __future__ import annotations

import numpy as np

from pipeline.metrics import imageutil


def edge_ssim_score(ref_rgb: np.ndarray, cand_rgb: np.ndarray) -> float:
    """SSIM in [0, 1] over the Sobel edge maps of the two top-align-padded renders."""
    a, b = imageutil.top_align_pad(ref_rgb, cand_rgb)
    ref_edges = imageutil.gradient_magnitude(imageutil.to_gray(a))
    cand_edges = imageutil.gradient_magnitude(imageutil.to_gray(b))
    return imageutil.ssim(ref_edges, cand_edges)
