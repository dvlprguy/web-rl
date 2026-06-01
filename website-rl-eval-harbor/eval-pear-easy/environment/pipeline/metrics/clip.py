"""High-level visual similarity via CLIP — a faithful port of Design2Code.

This mirrors `Design2Code/metrics/visual_score.py` from the official repo
(NoviScl/Design2Code), specifically `mask_bounding_boxes_with_inpainting`,
`rescale_and_mask`, and `calculate_clip_similarity_with_blocks`. We keep it in a
standalone module (separate from `perceptual.py`'s DINOv2/SigLIP2 backends) so
the canonical CLIP signal is never conflated with ours in ablations.

Their exact recipe, reproduced here:

  1. **Load** OpenAI CLIP ViT-B/32 via the `clip` package (``clip.load("ViT-B/32")``)
     — NOT HuggingFace transformers. ``encode_image`` returns the projected
     512-d image embedding directly.
  2. **Mask text** by Telea-inpainting (``cv2.inpaint(..., INPAINT_TELEA)``) the
     detected text boxes, so the score reflects layout/colour/structure, not
     OCR-able content — the paper's logistic-regression study found text content
     is the one dimension that does *not* track human preference.
  3. **Square-resize**: squash the (masked) page to a square at the SHORTER side
     with ``Image.LANCZOS``, then apply CLIP's own ``preprocess`` transform.
  4. **Score** = raw cosine of the two L2-normalised embeddings (``f1 @ f2.T``).
     Design2Code uses this raw cosine directly (it contributes 0.2·clip to their
     composite); we do NOT remap it to (1+cos)/2 — that would inflate/compress
     the range away from their reported scale.

Adapter notes for our pipeline: Design2Code's block detector yields normalised
``bbox = (x, y, w, h)`` ratios; our render-time ``.boxes.json`` sidecars give
pixel ``{x, y, w, h, text}``. We convert text boxes (``text > 0``) to ratios
before handing them to the (verbatim) masking code.

Heavy deps (torch / clip / cv2) are imported lazily and the model is cached, so
importing this module is cheap.
"""

from __future__ import annotations

import os

import numpy as np

from pipeline.metrics import imageutil

# OpenAI CLIP architecture name (Design2Code uses ViT-B/32). Overridable for ablation.
CLIP_CKPT = os.environ.get("CLIP_CKPT", "ViT-B/32")

# Whether to mask text before embedding (their inpainting step). On by default to
# match the paper and our design-only goal; disable to score raw pixels.
CLIP_MASK_TEXT = os.environ.get("CLIP_MASK_TEXT", "1") not in ("0", "false", "False")

_MODEL_CACHE: dict = {}


# --------------------------------------------------------------------------- #
# Model (OpenAI clip package — same weights & preprocess as Design2Code)
# --------------------------------------------------------------------------- #


def _load():
    """Load + cache (model, preprocess) for OpenAI CLIP ViT-B/32."""
    if "clip" in _MODEL_CACHE:
        return _MODEL_CACHE["clip"]
    import clip  # the OpenAI CLIP package (top-level), not this module
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, preprocess = clip.load(CLIP_CKPT, device=device)
    model.eval()
    _MODEL_CACHE["clip"] = (model, preprocess, device)
    return _MODEL_CACHE["clip"]


# --------------------------------------------------------------------------- #
# Text masking + square resize (verbatim port of their rescale_and_mask)
# --------------------------------------------------------------------------- #


def _boxes_to_ratios(boxes: list[dict] | None, w: int, h: int) -> list[tuple]:
    """Our pixel text boxes ({x,y,w,h,text}) → normalised (x,y,w,h) ratios.

    Only text-bearing boxes (``text > 0``) are kept — Design2Code's detector
    emits text blocks, so this reproduces "mask the text" on our richer sidecar.
    """
    if not boxes or w <= 0 or h <= 0:
        return []
    out = []
    for b in boxes:
        if b.get("text", 0) <= 0:
            continue
        out.append((b["x"] / w, b["y"] / h, b["w"] / w, b["h"] / h))
    return out


def mask_bounding_boxes_with_inpainting(rgb: np.ndarray, bounding_boxes: list[tuple]):
    """Telea-inpaint the given normalised bboxes. Verbatim from Design2Code.

    ``rgb`` is an (H, W, 3) uint8 array; ``bounding_boxes`` are (x, y, w, h)
    ratios in [0, 1]. Returns a PIL RGB image.
    """
    import cv2
    from PIL import Image

    image_cv = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    mask = np.zeros(image_cv.shape[:2], dtype=np.uint8)
    height, width = image_cv.shape[:2]
    for bbox in bounding_boxes:
        x_ratio, y_ratio, w_ratio, h_ratio = bbox
        x = int(x_ratio * width)
        y = int(y_ratio * height)
        w = int(w_ratio * width)
        h = int(h_ratio * height)
        mask[y : y + h, x : x + w] = 255
    inpainted = cv2.inpaint(image_cv, mask, 3, cv2.INPAINT_TELEA)
    return Image.fromarray(cv2.cvtColor(inpainted, cv2.COLOR_BGR2RGB))


def rescale_and_mask(rgb: np.ndarray, boxes: list[dict] | None):
    """Inpaint text (if enabled) then square-resize to the short side (LANCZOS).

    Faithful to Design2Code's ``rescale_and_mask``: if there are boxes to mask we
    inpaint, then resize to ``(min_side, min_side)`` with ``Image.LANCZOS`` —
    squashing the long dimension into a square so CLIP sees the whole page.
    """
    from PIL import Image

    h, w = rgb.shape[:2]
    ratios = _boxes_to_ratios(boxes, w, h) if CLIP_MASK_TEXT else []
    if ratios:
        img = mask_bounding_boxes_with_inpainting(rgb, ratios)
    else:
        img = Image.fromarray(rgb)

    width, height = img.size
    new_size = (width, width) if width < height else (height, height)
    return img.resize(new_size, Image.LANCZOS)


# --------------------------------------------------------------------------- #
# Embedding + score (verbatim port of calculate_clip_similarity_with_blocks)
# --------------------------------------------------------------------------- #


def _embed(rgb: np.ndarray, boxes: list[dict] | None) -> np.ndarray:
    """L2-normalised CLIP image embedding for one screenshot (text-masked)."""
    import torch

    model, preprocess, device = _load()
    image = preprocess(rescale_and_mask(rgb, boxes)).unsqueeze(0).to(device)
    with torch.no_grad():
        feats = model.encode_image(image)
    feats = feats / feats.norm(dim=-1, keepdim=True)
    return feats[0].float().cpu().numpy()


def clip_similarity(
    ref_rgb: np.ndarray,
    cand_rgb: np.ndarray,
    ref_boxes: list[dict] | None = None,
    cand_boxes: list[dict] | None = None,
) -> float:
    """Raw CLIP cosine similarity of the two screenshots — the Design2Code score.

    Returns the raw cosine ``(f_ref @ f_cand)`` exactly as Design2Code does (no
    (1+cos)/2 remap), clamped to [0, 1] so it composes with the other [0, 1]
    grader dimensions (CLIP image cosines are effectively non-negative here).
    """
    fr = _embed(ref_rgb, ref_boxes)
    fc = _embed(cand_rgb, cand_boxes)
    cos = float(np.dot(fr, fc))  # both unit-norm
    return max(0.0, min(1.0, cos))


# --------------------------------------------------------------------------- #
# CLI — score two images directly
# --------------------------------------------------------------------------- #


def _load_boxes(img_path: str) -> list[dict] | None:
    """Best-effort load of the ``<stem>.boxes.json`` sidecar next to an image."""
    import json
    from pathlib import Path

    p = Path(img_path)
    sidecar = p.with_suffix(".boxes.json")
    if not sidecar.exists() and p.suffix:
        sidecar = p.with_name(p.stem + ".boxes.json")
    if sidecar.exists():
        try:
            return json.loads(sidecar.read_text())
        except Exception:
            return None
    return None


def _main() -> None:
    import argparse

    ap = argparse.ArgumentParser(
        description="High-level CLIP visual similarity (Design2Code) between two screenshots."
    )
    ap.add_argument("reference", help="path to the reference image")
    ap.add_argument("candidate", help="path to the candidate image")
    ap.add_argument(
        "--no-mask",
        action="store_true",
        help="disable text-inpainting (score raw pixels, not text-masked)",
    )
    args = ap.parse_args()

    global CLIP_MASK_TEXT
    if args.no_mask:
        CLIP_MASK_TEXT = False

    ref = imageutil.load_rgb(args.reference)
    cand = imageutil.load_rgb(args.candidate)
    ref_boxes = _load_boxes(args.reference) if CLIP_MASK_TEXT else None
    cand_boxes = _load_boxes(args.candidate) if CLIP_MASK_TEXT else None

    score = clip_similarity(ref, cand, ref_boxes, cand_boxes)

    print(f"  arch        : {CLIP_CKPT}")
    print(f"  text-masked : {CLIP_MASK_TEXT}")
    print(f"  reference   : {args.reference}  {ref.shape[1]}x{ref.shape[0]}")
    print(f"  candidate   : {args.candidate}  {cand.shape[1]}x{cand.shape[0]}")
    print(f"  clip        : {score:.4f}   raw cosine (Design2Code)")


if __name__ == "__main__":
    _main()
