"""Shared image helpers for the grader's metric dimensions.

Pillow/numpy only; imported lazily by callers. Nothing here is model-heavy.
"""

from __future__ import annotations

import numpy as np


def load_rgb(path) -> np.ndarray:
    """Load an image as an (H, W, 3) uint8 RGB array."""
    from PIL import Image

    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.uint8)


def to_gray(rgb: np.ndarray) -> np.ndarray:
    """Rec. 601 luma → (H, W) uint8."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (0.299 * r + 0.587 * g + 0.114 * b).astype(np.uint8)


def top_align_pad(a: np.ndarray, b: np.ndarray, fill: int = 255) -> tuple[np.ndarray, np.ndarray]:
    """Top-left align two RGB images and pad both to the common (max H, max W).

    This is the D3 normalization: the reference and agent renders differ in
    height, so we pad the shorter to the taller (never resize — squishing would
    destroy the vertical-proportion signal). The height/width delta then shows up
    honestly as a filled band, which is exactly the fidelity penalty we want.
    """
    h = max(a.shape[0], b.shape[0])
    w = max(a.shape[1], b.shape[1])

    def _pad(x: np.ndarray) -> np.ndarray:
        out = np.full((h, w, 3), fill, dtype=x.dtype)
        out[: x.shape[0], : x.shape[1]] = x
        return out

    return _pad(a), _pad(b)


def downscale(rgb: np.ndarray, max_side: int) -> np.ndarray:
    """Aspect-preserving downscale so the long side ≤ max_side (for cheap metrics)."""
    from PIL import Image

    h, w = rgb.shape[:2]
    if max(h, w) <= max_side:
        return rgb
    scale = max_side / max(h, w)
    new = (max(1, round(w * scale)), max(1, round(h * scale)))  # PIL wants (W, H)
    im = Image.fromarray(rgb).resize(new, Image.BILINEAR)
    return np.asarray(im, dtype=np.uint8)


def resize_to(arr: np.ndarray, h: int, w: int) -> np.ndarray:
    """Resize a 2-D (gray) or 3-D (RGB) array to ``(h, w)`` via PIL (bilinear)."""
    from PIL import Image

    if arr.shape[0] == h and arr.shape[1] == w:
        return arr
    im = Image.fromarray(arr).resize((w, h), Image.BILINEAR)
    return np.asarray(im, dtype=arr.dtype)


def gradient_magnitude(gray: np.ndarray) -> np.ndarray:
    """Sobel gradient magnitude of a (H, W) grayscale image, normalised to [0, 255].

    An edge map emphasises typography (glyph outlines) and component borders while
    falling to ~0 in flat regions — so SSIM on it (see :func:`ssim`) measures shape
    and typography agreement instead of being dominated by large flat backgrounds.
    A lean Sobel stand-in for the Canny edge map used in Design2Code-style graders.
    """
    from scipy.ndimage import sobel

    g = gray.astype(np.float64)
    gx = sobel(g, axis=1)
    gy = sobel(g, axis=0)
    mag = np.hypot(gx, gy)
    peak = float(mag.max())
    return (mag / peak * 255.0) if peak > 0 else mag


def ssim(a: np.ndarray, b: np.ndarray, *, data_range: float = 255.0, win: int = 7) -> float:
    """Mean windowed SSIM between two equal-shape 2-D arrays, clamped to [0, 1].

    Standard Wang et al. (2004) SSIM with a uniform window — scipy.ndimage only, no
    skimage. Used for both within-block crops (:mod:`llem`) and full-image edge maps
    (:mod:`edge`).
    """
    from scipy.ndimage import uniform_filter

    if a.shape != b.shape:
        raise ValueError(f"ssim expects equal shapes, got {a.shape} vs {b.shape}")
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    c1 = (0.01 * data_range) ** 2
    c2 = (0.03 * data_range) ** 2
    mu_a = uniform_filter(a, win)
    mu_b = uniform_filter(b, win)
    mu_a2, mu_b2, mu_ab = mu_a * mu_a, mu_b * mu_b, mu_a * mu_b
    var_a = uniform_filter(a * a, win) - mu_a2
    var_b = uniform_filter(b * b, win) - mu_b2
    cov_ab = uniform_filter(a * b, win) - mu_ab
    ssim_map = ((2 * mu_ab + c1) * (2 * cov_ab + c2)) / (
        (mu_a2 + mu_b2 + c1) * (var_a + var_b + c2)
    )
    return float(np.clip(ssim_map.mean(), 0.0, 1.0))
