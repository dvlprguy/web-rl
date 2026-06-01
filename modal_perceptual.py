"""Run the perceptual + CLIP metrics on two images, on a Modal GPU.

Your laptop has neither the GPU nor the heavy deps (torch / transformers /
scikit-image / cv2) — Modal does. This wraps the REAL grader code
(`pipeline.metrics.perceptual` and `pipeline.metrics.clip`), so the scores you
get here are exactly what the verifier would compute; nothing is reimplemented.

    modal run modal_perceptual.py --reference ref.png --candidate cand.png
    modal run modal_perceptual.py --reference ref.png --candidate cand.png --model siglip2-naflex
    modal run modal_perceptual.py --reference ref.png --candidate cand.png --no-mask

Alongside the perceptual sub-scores it computes the Design2Code high-level CLIP
visual similarity (`pipeline.metrics.clip`). CLIP text-masking is ON by default;
the local entrypoint auto-ships each image's `<stem>.boxes.json` sidecar (when
present) so the inpainting matches what the verifier does. Use --no-mask to score
raw pixels.

First run downloads the model weights (~1.2 GB for dinov2-large, plus ~600 MB for
CLIP-ViT-B/32) into a persistent Modal Volume, so subsequent runs are fast. The
images and box sidecars are read locally and their bytes shipped to the GPU
container — no upload/mount juggling.
"""

from __future__ import annotations

import pathlib

import modal

# GPU container image: the perceptual deps + the local `pipeline` package source.
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")  # needed to pip-install OpenAI CLIP from its git repo
    .pip_install(
        "torch",
        "transformers",
        "scikit-image",
        "opencv-python-headless",  # cv2: Telea text-inpainting for the CLIP metric
        "ftfy",
        "regex",
        "git+https://github.com/openai/CLIP.git",  # OpenAI CLIP — Design2Code's exact model
        "pillow",
        "numpy",
    )
    # HF weights cache lives on a Volume (see below); point the libs at it.
    .env({"HF_HOME": "/cache/hf"})
    # Ship our actual grader code so `from pipeline.metrics import perceptual` works.
    .add_local_python_source("pipeline")
)

app = modal.App("perceptual-score", image=image)

# Persisted across runs so we download the multi-GB weights only once.
weights_cache = modal.Volume.from_name("hf-cache", create_if_missing=True)


@app.function(gpu="A10G", volumes={"/cache": weights_cache}, timeout=900)
def score(
    ref_bytes: bytes,
    cand_bytes: bytes,
    model: str,
    embed_w: float,
    mask_text: bool = True,
    ref_boxes_json: bytes | None = None,
    cand_boxes_json: bytes | None = None,
) -> dict:
    """Score one pair on the GPU and return the sub-scores."""
    import json
    import os
    import tempfile

    # perceptual/clip read their env config at import time — set BEFORE importing.
    os.environ["EMBEDDING_MODEL"] = model
    os.environ["CLIP_MASK_TEXT"] = "1" if mask_text else "0"

    import numpy as np

    from pipeline.metrics import clip, imageutil, perceptual

    with tempfile.TemporaryDirectory() as d:
        ref_path = pathlib.Path(d) / "ref.png"
        cand_path = pathlib.Path(d) / "cand.png"
        ref_path.write_bytes(ref_bytes)
        cand_path.write_bytes(cand_bytes)
        ref = imageutil.load_rgb(ref_path)
        cand = imageutil.load_rgb(cand_path)

    import torch

    # Raw GLOBAL embedding (CLS pooler), so we see the spread (1+cos)/2 hides.
    fr = perceptual._embed(ref)
    fc = perceptual._embed(cand)
    raw_cos = float(np.dot(fr, fc))  # both unit-norm
    l2 = float(np.linalg.norm(fr - fc))  # Euclidean distance in embedding space

    # DENSE patch-token similarity (dinov2 only): top-align+pad both so the patch
    # grids line up, take per-location patch cosine, average. This is sensitive to
    # LOCAL layout/colour shifts the global CLS token washes out — the hypothesis
    # being it spreads dynamic range across the plausible-replica region.
    dense_cos = None
    if model == "dinov2":
        mdl, _ = perceptual._load("dinov2")
        ra, ca = imageutil.top_align_pad(ref, cand)

        def _patches(rgb):
            pv = perceptual._dinov2_pixels(rgb)
            if torch.cuda.is_available():
                pv = pv.cuda()
            with torch.no_grad():
                hs = mdl(pixel_values=pv).last_hidden_state[0]  # [1+N, D]
            p = hs[1:]  # drop CLS -> [N, D]
            return p / p.norm(dim=-1, keepdim=True)

        pr, pc = _patches(ra), _patches(ca)
        if pr.shape == pc.shape:
            dense_cos = float((pr * pc).sum(-1).mean().cpu())

    e = perceptual.embedding_similarity(ref, cand)  # = (1 + raw_cos) / 2
    s = perceptual.ssim_similarity(ref, cand)

    # Design2Code high-level CLIP visual similarity. Text-masking (if enabled)
    # needs the render-time box sidecars; ship them alongside the images.
    ref_boxes = json.loads(ref_boxes_json) if ref_boxes_json else None
    cand_boxes = json.loads(cand_boxes_json) if cand_boxes_json else None
    clip_sim = clip.clip_similarity(ref, cand, ref_boxes, cand_boxes)

    weights_cache.commit()  # persist any newly downloaded weights
    return {
        "backend": model,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
        "ref_shape": [int(ref.shape[1]), int(ref.shape[0])],
        "cand_shape": [int(cand.shape[1]), int(cand.shape[0])],
        "raw_cos": raw_cos,
        "dense_cos": dense_cos,
        "l2": l2,
        "embedding": e,
        "ssim": s,
        "perceptual": embed_w * e + (1.0 - embed_w) * s,
        "embed_w": embed_w,
        "clip": clip_sim,
        "clip_ckpt": clip.CLIP_CKPT,
        "clip_masked": clip.CLIP_MASK_TEXT,
    }


def _boxes_bytes(image_path: str) -> bytes | None:
    """Read the `<stem>.boxes.json` sidecar next to an image, if it exists."""
    p = pathlib.Path(image_path)
    sidecar = p.with_suffix(".boxes.json")
    if not sidecar.exists():
        sidecar = p.with_name(p.stem + ".boxes.json")
    return sidecar.read_bytes() if sidecar.exists() else None


@app.local_entrypoint()
def main(
    reference: str,
    candidate: str,
    model: str = "dinov2",
    embed_w: float = 0.8,
    no_mask: bool = False,
):
    ref_bytes = pathlib.Path(reference).read_bytes()
    cand_bytes = pathlib.Path(candidate).read_bytes()
    mask_text = not no_mask
    ref_boxes = _boxes_bytes(reference) if mask_text else None
    cand_boxes = _boxes_bytes(candidate) if mask_text else None
    r = score.remote(
        ref_bytes, cand_bytes, model, embed_w, mask_text, ref_boxes, cand_boxes
    )

    print(f"  backend     : {r['backend']}  (on {r['gpu']})")
    print(f"  reference   : {reference}  {r['ref_shape'][0]}x{r['ref_shape'][1]}")
    print(f"  candidate   : {candidate}  {r['cand_shape'][0]}x{r['cand_shape'][1]}")
    print(f"  raw cosine  : {r['raw_cos']:.6f}   <- GLOBAL CLS agreement")
    dc = r.get("dense_cos")
    if dc is not None:
        print(
            f"  dense cosine: {dc:.6f}   <- DENSE patch agreement (the candidate fix)"
        )
    print(f"  l2 distance : {r['l2']:.4f}")
    print(f"  embedding   : {r['embedding']:.4f}   ((1+cos)/2 — squashed)")
    print(f"  ssim        : {r['ssim']:.4f}")
    ew = r["embed_w"]
    print(f"  perceptual  : {r['perceptual']:.4f}   ({ew:g}·embed + {1 - ew:g}·ssim)")
    masked = "text-masked" if r["clip_masked"] else "raw pixels"
    print(f"  clip        : {r['clip']:.4f}   <- Design2Code high-level ({masked})")
