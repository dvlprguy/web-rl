"""Dimension 1 — perceptual similarity = vision-embedding cosine + SSIM.

The embedding is a SINGLE, SELECTABLE backend (``EMBEDDING_MODEL``), never an
ensemble — exactly one model runs per grading pass:

  * ``dinov2``         — DINOv2 ViT-L/14, fed the full rectangular page
                         (aspect-preserving, long-side capped, dims ×14).
  * ``siglip2-naflex`` — SigLIP2-NaFlex, native variable aspect via a patch budget.

Both still downscale (no model reads a 2700px page natively); we keep resolution
high so text *appearance* survives. Aspect is preserved either way. The degradation
ladder picks the default; here we just honour the selection.

    perceptual = 0.8 · embed_sim + 0.2 · ssim     (embed → "right screen",
                                                    ssim  → precise layout)

Heavy deps (torch / transformers / scikit-image) are imported lazily, and the
model is loaded once and cached, so importing this module is cheap.
"""

from __future__ import annotations

import os

import numpy as np

from pipeline.metrics import imageutil

# Backend selection + checkpoints (overridable via env for exact HF ids).
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "dinov2")
DINOV2_CKPT = os.environ.get("DINOV2_CKPT", "facebook/dinov2-large")
# NaFlex ships only `base` and `so400m` (no `large`); so400m is the strong SOTA one.
SIGLIP2_CKPT = os.environ.get("SIGLIP2_CKPT", "google/siglip2-so400m-patch16-naflex")

# DINOv2 input shaping. Long-side cap bounds the token count on tall pages; ×14 so
# it tiles into whole patches. Kept high (GPU-afforded) to preserve text detail.
DINOV2_PATCH = 14
DINOV2_LONG_SIDE = int(os.environ.get("DINOV2_LONG_SIDE", "1288"))
SIGLIP2_MAX_PATCHES = int(os.environ.get("SIGLIP2_MAX_PATCHES", "1024"))

_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)

_MODEL_CACHE: dict = {}


# --------------------------------------------------------------------------- #
# Embedding backends
# --------------------------------------------------------------------------- #


def _load(name: str):
    """Load + cache (model, processor-or-None) for the selected backend."""
    if name in _MODEL_CACHE:
        return _MODEL_CACHE[name]
    import torch
    from transformers import AutoModel

    if name == "dinov2":
        model = AutoModel.from_pretrained(DINOV2_CKPT)
        proc = None
    elif name == "siglip2-naflex":
        from transformers import AutoProcessor

        model = AutoModel.from_pretrained(SIGLIP2_CKPT)
        proc = AutoProcessor.from_pretrained(SIGLIP2_CKPT)
    else:
        raise ValueError(f"unknown EMBEDDING_MODEL: {name!r}")

    model.eval()
    if torch.cuda.is_available():
        model = model.cuda()
    _MODEL_CACHE[name] = (model, proc)
    return _MODEL_CACHE[name]


def _dinov2_pixels(rgb: np.ndarray):
    """Aspect-preserving resize (long side ≤ cap, dims ×14) → normalised tensor."""
    import torch
    from PIL import Image

    h, w = rgb.shape[:2]
    scale = min(1.0, DINOV2_LONG_SIDE / max(h, w))
    nh = max(DINOV2_PATCH, int(round(h * scale / DINOV2_PATCH)) * DINOV2_PATCH)
    nw = max(DINOV2_PATCH, int(round(w * scale / DINOV2_PATCH)) * DINOV2_PATCH)
    im = Image.fromarray(rgb).resize((nw, nh), Image.BILINEAR)
    t = torch.from_numpy(np.asarray(im, dtype=np.float32) / 255.0).permute(2, 0, 1)
    mean = torch.tensor(_IMAGENET_MEAN).view(3, 1, 1)
    std = torch.tensor(_IMAGENET_STD).view(3, 1, 1)
    return ((t - mean) / std).unsqueeze(0)


def _embed(rgb: np.ndarray) -> np.ndarray:
    """Return a unit-norm embedding vector for one RGB image."""
    import torch

    model, proc = _load(EMBEDDING_MODEL)
    with torch.no_grad():
        if EMBEDDING_MODEL == "dinov2":
            pv = _dinov2_pixels(rgb)
            if torch.cuda.is_available():
                pv = pv.cuda()
            out = model(pixel_values=pv)
            vec = out.pooler_output[0]  # CLS token (post-layernorm)
        else:  # siglip2-naflex
            from PIL import Image

            inputs = proc(
                images=Image.fromarray(rgb),
                max_num_patches=SIGLIP2_MAX_PATCHES,
                return_tensors="pt",
            )
            if torch.cuda.is_available():
                inputs = {k: v.cuda() for k, v in inputs.items()}
            vec = model.get_image_features(**inputs)[0]
    v = vec.float().cpu().numpy()
    n = np.linalg.norm(v)
    return v / n if n else v


# --------------------------------------------------------------------------- #
# Sub-scores + combination
# --------------------------------------------------------------------------- #


def embedding_similarity(ref_rgb: np.ndarray, cand_rgb: np.ndarray) -> float:
    """Cosine of the two embeddings, mapped to [0, 1]: (1 + cos) / 2."""
    fr, fc = _embed(ref_rgb), _embed(cand_rgb)
    cos = float(np.dot(fr, fc))  # both unit-norm
    return max(0.0, min(1.0, (1.0 + cos) / 2.0))


def ssim_similarity(ref_rgb: np.ndarray, cand_rgb: np.ndarray) -> float:
    """SSIM on the D3-normalised (top-aligned, padded) grayscale renders → [0, 1]."""
    from skimage.metrics import structural_similarity

    a, b = imageutil.top_align_pad(ref_rgb, cand_rgb)
    s = structural_similarity(imageutil.to_gray(a), imageutil.to_gray(b), data_range=255)
    return max(0.0, min(1.0, (s + 1.0) / 2.0))


def perceptual_score(
    ref_rgb: np.ndarray, cand_rgb: np.ndarray, embed_w: float = 0.8
) -> float:
    """0.8 · embedding + 0.2 · SSIM (weights configurable)."""
    e = embedding_similarity(ref_rgb, cand_rgb)
    s = ssim_similarity(ref_rgb, cand_rgb)
    return embed_w * e + (1.0 - embed_w) * s


# --------------------------------------------------------------------------- #
# CLI — score two images directly
# --------------------------------------------------------------------------- #


def _main() -> None:
    import argparse

    ap = argparse.ArgumentParser(
        description="Perceptual similarity (embedding + SSIM) between two images."
    )
    ap.add_argument("reference", help="path to the reference image")
    ap.add_argument("candidate", help="path to the candidate image")
    ap.add_argument(
        "-m",
        "--model",
        choices=["dinov2", "siglip2-naflex"],
        help="embedding backend (overrides EMBEDDING_MODEL env; default dinov2)",
    )
    ap.add_argument(
        "--embed-w",
        type=float,
        default=0.8,
        help="weight on the embedding term (rest goes to SSIM); default 0.8",
    )
    args = ap.parse_args()

    # Honour the flag by setting the module-level backend before anything loads.
    global EMBEDDING_MODEL
    if args.model:
        EMBEDDING_MODEL = args.model

    ref = imageutil.load_rgb(args.reference)
    cand = imageutil.load_rgb(args.candidate)

    e = embedding_similarity(ref, cand)
    s = ssim_similarity(ref, cand)
    score = args.embed_w * e + (1.0 - args.embed_w) * s

    print(f"  backend     : {EMBEDDING_MODEL}")
    print(f"  reference   : {args.reference}  {ref.shape[1]}x{ref.shape[0]}")
    print(f"  candidate   : {args.candidate}  {cand.shape[1]}x{cand.shape[0]}")
    print(f"  embedding   : {e:.4f}")
    print(f"  ssim        : {s:.4f}")
    print(f"  perceptual  : {score:.4f}   ({args.embed_w:g}·embed + {1 - args.embed_w:g}·ssim)")


if __name__ == "__main__":
    _main()
