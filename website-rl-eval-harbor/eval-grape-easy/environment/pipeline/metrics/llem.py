"""Low-Level Element Matching (LLEM) — Design2Code (Si et al. 2024, arXiv:2403.03163).

The four fine-grained, diagnostic similarity metrics from Design2Code, all derived
from ONE block detection + matching pass over the two rendered screenshots:

    block_match  — was every text element reproduced, at the right size, with no
                   missing/hallucinated blocks?  (size-weighted recall+precision)
    text         — character agreement of matched blocks (difflib ratio)
    position     — how close matched blocks land (normalised centre distance)
    text_color   — colour agreement of matched block text (CIEDE2000)

(Design2Code's fifth metric, high-level CLIP similarity, lives in ``metrics.clip``;
it is intentionally NOT recomputed here.)

Why we keep our own detector
----------------------------
Design2Code detects blocks with ``get_blocks_ocr_free``: it recolours every text
element in the *HTML*, renders twice, and diffs to recover each block's bbox and
colour. That is DOM-based — exactly the dependence we're avoiding (the reason we
reached for Block-Match in the first place). So we detect blocks from PIXELS with
Tesseract and estimate each block's text colour by sampling the screenshot. This is
faithful to the four metric *definitions* (which is what Design2Code's human-
correlation study in Table 2 actually validates) while staying screenshot-only.

What's validated vs. what we changed
------------------------------------
Faithful to the source (``metrics/visual_score.py``): the block-match area formula
(Eq. 1-2), the <0.5 text-similarity match filter, ``difflib.SequenceMatcher.ratio``
as the text metric/cost, the position formula ``1 - max(|Δcx|, |Δcy|)`` on
normalised centres, and CIEDE2000 colour similarity ``max(0, 1 - ΔE/100)``.
Deviations (documented, to revisit on the ladder): pixel OCR instead of the DOM
recolour detector; pixel-sampled block colour; and we omit their context-bonus
(``adjust_cost_for_context``) and adjacent-block merging (``find_possible_merge``),
which compensate for *their* detector's over-segmentation — Tesseract already groups
words into lines.

Per-metric weighting note: in Design2Code's Table 2, Position (+0.76) and Block-Match
(+0.74) are the strongest human-aligned signals; text *content* is *negatively*
correlated (-0.35). So `text` is implemented here but left OFF in the grader's
default weights — it's a diagnostic, not a reward channel (see grader.py).

Dependencies: the ``tesseract`` binary (apt: ``tesseract-ocr``; brew: ``tesseract``;
or set ``$TESSERACT_CMD``). CIEDE2000 is implemented in-module (no colormath/skimage),
so this stays self-contained and deterministic.
"""

from __future__ import annotations

import csv
import io
import math
import os
import shutil
import subprocess
from dataclasses import dataclass
from difflib import SequenceMatcher

import numpy as np

# Drop OCR detections below this confidence (0-100); Tesseract emits -1 for
# structural rows. Rendered text scores high, so this mostly culls noise.
_MIN_CONF = 40.0
# An assigned pair counts as "matched" only if its text similarity clears this
# (Design2Code's exact threshold). Below it, both blocks fall to the unmatched sets.
_MATCH_THRESHOLD = 0.5

# The metric names this module produces (the grader's LLEM dimension group). The
# first four are Design2Code's LLEM metrics; `block_color` and `block_ssim` are
# region-level additions (à la Design2Code v2) that reuse the SAME
# matched set to score what the four are blind to — the colour of the matched
# REGION (not just the text glyph) and within-block render fidelity.
LLEM_DIMENSIONS = frozenset(
    {"block_match", "text", "position", "text_color", "block_color", "block_ssim"}
)
# The two that need pixel crops (and so the rgb arrays), not just block geometry.
_PIXEL_DIMENSIONS = frozenset({"block_color", "block_ssim"})


@dataclass(frozen=True)
class TextBlock:
    """One detected line of text. Coordinates are NORMALISED to [0, 1] by the
    block's own image dimensions (x, w by width; y, h by height) — matching
    Design2Code, so position is a relative-layout signal. ``color`` is the
    estimated text colour as an RGB triple in [0, 255]."""

    text: str
    x: float
    y: float
    w: float
    h: float
    color: tuple[int, int, int]

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0


# --------------------------------------------------------------------------- #
# Block detection (Tesseract → text + bbox + sampled colour)
# --------------------------------------------------------------------------- #

# Tesseract TSV columns (fixed order), level 5 = a single word.
_COL = {
    "level": 0, "block_num": 2, "par_num": 3, "line_num": 4,
    "left": 6, "top": 7, "width": 8, "height": 9, "conf": 10, "text": 11,
}  # fmt: skip
_WORD_LEVEL = "5"


def _run_tesseract_tsv(png_path) -> str:
    """Run `tesseract <img> stdout tsv` and return the raw TSV text."""
    binary = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    if not binary:
        raise RuntimeError(
            "tesseract binary not found — install it (apt: tesseract-ocr, "
            "brew: tesseract) or set $TESSERACT_CMD"
        )
    proc = subprocess.run(
        [binary, str(png_path), "stdout", "tsv"],
        capture_output=True,
        check=True,  # nonzero exit → CalledProcessError (don't silently score 0)
    )
    return proc.stdout.decode("utf-8", errors="replace")


def _estimate_text_color(
    rgb: np.ndarray, x0: int, y0: int, x1: int, y1: int
) -> tuple[int, int, int]:
    """Estimate a text line's colour from its pixel bbox: the background is the
    dominant (most common) colour, the text is the minority that differs from it.
    Returns the median of those text pixels as RGB [0, 255]."""
    crop = rgb[max(0, y0) : max(y0 + 1, y1), max(0, x0) : max(x0 + 1, x1)]
    flat = crop.reshape(-1, 3)
    if len(flat) == 0:
        return (0, 0, 0)
    # Quantise to find the background mode robustly.
    quant = (flat // 16) * 16
    colors, counts = np.unique(quant, axis=0, return_counts=True)
    bg = colors[counts.argmax()].astype(np.int32)
    dist = np.linalg.norm(flat.astype(np.int32) - bg, axis=1)
    text_px = flat[dist > 40]
    if len(text_px) < max(5, int(0.02 * len(flat))):
        # Low contrast / mostly background: fall back to the pixels furthest from bg.
        thresh = np.percentile(dist, 90)
        text_px = flat[dist >= thresh]
    if len(text_px) == 0:
        text_px = flat
    return tuple(int(v) for v in np.median(text_px, axis=0))


def detect_blocks(png_path, min_conf: float = _MIN_CONF) -> list[TextBlock]:
    """OCR an image into text blocks — one per detected line.

    Words are grouped by Tesseract's (block, paragraph, line) numbering and merged
    into a single block: text joined, bbox unioned, colour sampled from the union
    bbox. Line granularity is the sweet spot — coarser (whole paragraph) loses
    headings as distinct salient blocks; finer (per word) makes matching noisy.
    """
    from PIL import Image

    with Image.open(png_path) as im:
        rgb = np.asarray(im.convert("RGB"), dtype=np.uint8)
    img_h, img_w = rgb.shape[:2]

    tsv = _run_tesseract_tsv(png_path)
    # QUOTE_NONE: Tesseract doesn't quote fields, and page text routinely contains
    # bare quote characters that would otherwise hijack the parser.
    reader = csv.reader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)

    groups: dict[tuple[str, str, str], dict] = {}
    for row in reader:
        if len(row) <= _COL["text"] or row[_COL["level"]] != _WORD_LEVEL:
            continue  # skip header + non-word (page/block/para/line) rows
        text = row[_COL["text"]].strip()
        try:
            conf = float(row[_COL["conf"]])
        except ValueError:
            conf = -1.0
        if not text or conf < min_conf:
            continue
        key = (row[_COL["block_num"]], row[_COL["par_num"]], row[_COL["line_num"]])
        left, top = float(row[_COL["left"]]), float(row[_COL["top"]])
        right, bottom = (
            left + float(row[_COL["width"]]),
            top + float(row[_COL["height"]]),
        )
        g = groups.get(key)
        if g is None:
            groups[key] = {
                "words": [text],
                "l": left,
                "t": top,
                "r": right,
                "b": bottom,
            }
        else:
            g["words"].append(text)
            g["l"], g["t"] = min(g["l"], left), min(g["t"], top)
            g["r"], g["b"] = max(g["r"], right), max(g["b"], bottom)

    blocks: list[TextBlock] = []
    for g in groups.values():
        color = _estimate_text_color(
            rgb, int(g["l"]), int(g["t"]), int(g["r"]), int(g["b"])
        )
        blocks.append(
            TextBlock(
                text=" ".join(g["words"]),
                x=g["l"] / img_w,
                y=g["t"] / img_h,
                w=(g["r"] - g["l"]) / img_w,
                h=(g["b"] - g["t"]) / img_h,
                color=color,
            )
        )
    return blocks


# --------------------------------------------------------------------------- #
# Matching (Design2Code: Jonker-Volgenant on text similarity, then <0.5 filter)
# --------------------------------------------------------------------------- #


def text_similarity(a: str, b: str) -> float:
    """Design2Code's text metric: ``difflib.SequenceMatcher.ratio()`` (gestalt /
    Ratcliff-Obershelp), case-insensitive, in [0, 1]. Used both as the matching
    cost and as the reported ``text`` score."""
    a, b = a.strip().lower(), b.strip().lower()
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def match_blocks(
    ref: list[TextBlock], cand: list[TextBlock], threshold: float = _MATCH_THRESHOLD
) -> list[tuple[int, int, float]]:
    """Optimally assign ref↔cand blocks to maximise total text similarity
    (``scipy.linear_sum_assignment`` = the modified Jonker-Volgenant algorithm,
    Design2Code's exact choice), then drop pairs below ``threshold``. Returns
    (ref_idx, cand_idx, text_similarity) for each surviving match."""
    if not ref or not cand:
        return []
    from scipy.optimize import linear_sum_assignment

    sim = np.zeros((len(ref), len(cand)), dtype=np.float64)
    for i, r in enumerate(ref):
        for j, c in enumerate(cand):
            sim[i, j] = text_similarity(r.text, c.text)

    rows, cols = linear_sum_assignment(sim, maximize=True)
    return [
        (int(i), int(j), float(sim[i, j]))
        for i, j in zip(rows, cols)
        if sim[i, j] >= threshold
    ]


# --------------------------------------------------------------------------- #
# CIEDE2000 (self-contained; no colormath/skimage)
# --------------------------------------------------------------------------- #


def _srgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """sRGB [0,255] → CIE Lab (D65), the standard pipeline."""
    r, g, b = (c / 255.0 for c in rgb)

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = lin(r), lin(g), lin(b)
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _ciede2000(
    lab1: tuple[float, float, float], lab2: tuple[float, float, float]
) -> float:
    """CIEDE2000 colour difference ΔE00 between two Lab colours."""
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    avg_c = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(avg_c**7 / (avg_c**7 + 25**7))) if avg_c > 0 else 0.0
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360

    dlp = l2 - l1
    dcp = c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    else:
        dh = h2p - h1p
        dh -= 360 if dh > 180 else (-360 if dh < -180 else 0)
        dhp = dh
    dHp = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp) / 2)

    avg_l = (l1 + l2) / 2
    avg_cp = (c1p + c2p) / 2
    if c1p * c2p == 0:
        avg_hp = h1p + h2p
    elif abs(h1p - h2p) > 180:
        avg_hp = (h1p + h2p + 360) / 2 if (h1p + h2p) < 360 else (h1p + h2p - 360) / 2
    else:
        avg_hp = (h1p + h2p) / 2

    t = (
        1
        - 0.17 * math.cos(math.radians(avg_hp - 30))
        + 0.24 * math.cos(math.radians(2 * avg_hp))
        + 0.32 * math.cos(math.radians(3 * avg_hp + 6))
        - 0.20 * math.cos(math.radians(4 * avg_hp - 63))
    )
    d_theta = 30 * math.exp(-(((avg_hp - 275) / 25) ** 2))
    rc = 2 * math.sqrt(avg_cp**7 / (avg_cp**7 + 25**7)) if avg_cp > 0 else 0.0
    sl = 1 + (0.015 * (avg_l - 50) ** 2) / math.sqrt(20 + (avg_l - 50) ** 2)
    sc = 1 + 0.045 * avg_cp
    sh = 1 + 0.015 * avg_cp * t
    rt = -math.sin(math.radians(2 * d_theta)) * rc

    return math.sqrt(
        (dlp / sl) ** 2
        + (dcp / sc) ** 2
        + (dHp / sh) ** 2
        + rt * (dcp / sc) * (dHp / sh)
    )


def color_similarity(rgb1: tuple[int, int, int], rgb2: tuple[int, int, int]) -> float:
    """Design2Code's normalised CIEDE2000 colour similarity: ``max(0, 1 - ΔE/100)``."""
    de = _ciede2000(_srgb_to_lab(rgb1), _srgb_to_lab(rgb2))
    return max(0.0, 1 - de / 100)


# --------------------------------------------------------------------------- #
# The four scores (each in [0, 1]; all consume the SAME matched set)
# --------------------------------------------------------------------------- #


def _matched_quality(ref, cand, matches, per_pair) -> float:
    """Mean of a per-matched-pair score, with Design2Code's degenerate handling:
    both sides empty → 1.0 (nothing to disagree on), otherwise no matches → 0.0."""
    if matches:
        return float(np.mean([per_pair(i, j, s) for i, j, s in matches]))
    return 1.0 if not ref and not cand else 0.0


def block_match_score(ref, cand, matches) -> float:
    """Size-weighted Block-Match (Design2Code Eq. 1-2): the share of total block
    area (across both images) that found a partner. Missing reference blocks and
    hallucinated candidate blocks are both unmatched, so both lower the score."""
    total = sum(b.area for b in ref) + sum(b.area for b in cand)
    if total <= 0:
        return 1.0  # neither side has text blocks → trivial agreement
    matched = sum(ref[i].area + cand[j].area for i, j, _ in matches)
    return matched / total


def text_score(ref, cand, matches) -> float:
    """Mean text similarity over matched blocks (Design2Code ``SequenceMatcher``)."""
    return _matched_quality(ref, cand, matches, lambda i, j, s: s)


def position_score(ref, cand, matches) -> float:
    """Mean ``1 - max(|Δcx|, |Δcy|)`` over matched blocks, normalised centres."""
    return _matched_quality(
        ref,
        cand,
        matches,
        lambda i, j, s: max(
            0.0, 1 - max(abs(ref[i].cx - cand[j].cx), abs(ref[i].cy - cand[j].cy))
        ),
    )


def text_color_score(ref, cand, matches) -> float:
    """Mean CIEDE2000 colour similarity over matched blocks' estimated text colour."""
    return _matched_quality(
        ref,
        cand,
        matches,
        lambda i, j, s: color_similarity(ref[i].color, cand[j].color),
    )


# --------------------------------------------------------------------------- #
# Region-level scores (need pixel crops; reuse the SAME matched set)
# --------------------------------------------------------------------------- #


def _pixel_bbox(block: TextBlock, img_w: int, img_h: int) -> tuple[int, int, int, int]:
    """Recover a matched block's pixel bbox from its [0,1]-normalised coords."""
    x0 = max(0, min(int(round(block.x * img_w)), img_w - 1))
    y0 = max(0, min(int(round(block.y * img_h)), img_h - 1))
    x1 = max(x0 + 1, min(int(round((block.x + block.w) * img_w)), img_w))
    y1 = max(y0 + 1, min(int(round((block.y + block.h) * img_h)), img_h))
    return x0, y0, x1, y1


def block_color_score(ref, cand, matches, ref_rgb, cand_rgb) -> float:
    """Area-weighted mean-colour CIEDE2000 over matched REGION crops.

    Unlike ``text_color`` (which samples only the glyph colour) this compares the
    mean colour of each matched region — so it sees the section/surface colour the
    glyph sampler ignores. Being per-matched-region, it is free of the whole-page
    background dominance that flattens the global-histogram ``color`` dim (the
    grader's D10 weakness). v1 = mean colour; per-pixel ΔE is the documented v2."""
    if not matches:
        return 1.0 if not ref and not cand else 0.0
    rh, rw = ref_rgb.shape[:2]
    ch, cw = cand_rgb.shape[:2]
    weighted, total = 0.0, 0.0
    for i, j, _ in matches:
        rx0, ry0, rx1, ry1 = _pixel_bbox(ref[i], rw, rh)
        cx0, cy0, cx1, cy1 = _pixel_bbox(cand[j], cw, ch)
        rmean = ref_rgb[ry0:ry1, rx0:rx1].reshape(-1, 3).mean(axis=0)
        cmean = cand_rgb[cy0:cy1, cx0:cx1].reshape(-1, 3).mean(axis=0)
        sim = color_similarity(
            tuple(int(v) for v in rmean), tuple(int(v) for v in cmean)
        )
        area = (rx1 - rx0) * (ry1 - ry0)
        weighted += sim * area
        total += area
    return weighted / total if total > 0 else 0.0


def block_internal_ssim_score(ref, cand, matches, ref_rgb, cand_rgb) -> float:
    """Area-weighted SSIM over matched REGION crops — within-block render fidelity.

    Catches what block-match/position miss: a matched line rendered in the wrong
    font weight/family, wrong fill, or with a missing inline glyph still lands in
    the right place but looks different inside. Agent crop is resized to the ref
    crop before SSIM. Crops too small for the SSIM window are skipped."""
    from pipeline.metrics import imageutil

    if not matches:
        return 1.0 if not ref and not cand else 0.0
    rh, rw = ref_rgb.shape[:2]
    ch, cw = cand_rgb.shape[:2]
    ref_gray = imageutil.to_gray(ref_rgb)
    cand_gray = imageutil.to_gray(cand_rgb)
    weighted, total = 0.0, 0.0
    for i, j, _ in matches:
        rx0, ry0, rx1, ry1 = _pixel_bbox(ref[i], rw, rh)
        cx0, cy0, cx1, cy1 = _pixel_bbox(cand[j], cw, ch)
        ref_crop = ref_gray[ry0:ry1, rx0:rx1]
        cand_crop = cand_gray[cy0:cy1, cx0:cx1]
        if ref_crop.shape[0] < 7 or ref_crop.shape[1] < 7:
            continue  # smaller than the SSIM window
        cand_crop = imageutil.resize_to(cand_crop, ref_crop.shape[0], ref_crop.shape[1])
        area = (rx1 - rx0) * (ry1 - ry0)
        weighted += imageutil.ssim(ref_crop, cand_crop) * area
        total += area
    # Matched but nothing measurable (all crops sub-window) → no penalty.
    return weighted / total if total > 0 else 1.0


_TEXT_SCORERS = {
    "block_match": block_match_score,
    "text": text_score,
    "position": position_score,
    "text_color": text_color_score,
}


def llem_scores(
    ref_png, cand_png, dims=None, threshold: float = _MATCH_THRESHOLD
) -> dict[str, float]:
    """Detect + match once, then compute the requested LLEM scores. ``dims`` is a
    subset of ``LLEM_DIMENSIONS`` (default: all). This is what the grader calls, so
    the expensive OCR + assignment runs a single time per page pair. The rgb arrays
    are loaded only when a pixel-crop dim (``block_color``/``block_ssim``) is asked
    for."""
    wanted = LLEM_DIMENSIONS if dims is None else (set(dims) & LLEM_DIMENSIONS)
    ref = detect_blocks(ref_png)
    cand = detect_blocks(cand_png)
    matches = match_blocks(ref, cand, threshold)

    scores = {
        dim: _TEXT_SCORERS[dim](ref, cand, matches)
        for dim in wanted
        if dim in _TEXT_SCORERS
    }

    if wanted & _PIXEL_DIMENSIONS:
        from pipeline.metrics import imageutil

        ref_rgb = imageutil.load_rgb(ref_png)
        cand_rgb = imageutil.load_rgb(cand_png)
        if "block_color" in wanted:
            scores["block_color"] = block_color_score(
                ref, cand, matches, ref_rgb, cand_rgb
            )
        if "block_ssim" in wanted:
            scores["block_ssim"] = block_internal_ssim_score(
                ref, cand, matches, ref_rgb, cand_rgb
            )
    return scores
