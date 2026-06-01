"""'What the grader sees' — one page rendered four ways, one per signal family, so the
grader reads as a deliberate multi-signal system rather than a black box.
Writes docs/figures/grader_anatomy.png.

    TMPDIR="$PWD/.gtmp" venv/bin/python scripts/make_grader_anatomy.py   # tesseract needs a readable TMPDIR
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from pipeline.metrics import imageutil  # noqa: E402
from pipeline.metrics.llem import detect_blocks  # noqa: E402

TASK = "eval-pear-easy"
PAGE = "home"
CROP_H = 980  # show the first viewport-and-a-bit so overlays are legible
REF = Path(f"website-rl-eval-harbor/{TASK}/tests/reference")


def main():
    png = REF / f"{PAGE}.png"
    rgb = imageutil.load_rgb(png)
    H, W = rgb.shape[:2]
    ch = min(CROP_H, H)
    crop = rgb[:ch]
    boxes = json.loads((REF / f"{PAGE}.boxes.json").read_text())
    edges = imageutil.gradient_magnitude(imageutil.to_gray(rgb))[:ch]
    blocks = detect_blocks(png)  # OCR text lines (normalised coords)

    fig, ax = plt.subplots(2, 2, figsize=(12, 13))

    # 1 — the rendered page
    ax[0, 0].imshow(crop)
    ax[0, 0].set_title("① the page (target render)", fontsize=12, loc="left")

    # 2 — structure: rendered DOM boxes
    ax[0, 1].imshow(crop)
    for b in boxes:
        if b["y"] < ch:
            ax[0, 1].add_patch(Rectangle((b["x"], b["y"]), b["w"], b["h"],
                                         fill=False, edgecolor="#2e8b57", lw=0.8, alpha=0.9))
    ax[0, 1].set_title(f"② structure — {len(boxes)} rendered DOM boxes "
                       "(layout backbone, honest zero)", fontsize=12, loc="left")

    # 3 — block_color / text_color: OCR text blocks, outlined in their sampled colour
    ax[1, 0].imshow(crop)
    n_shown = 0
    for blk in blocks:
        x, y, w, h = blk.x * W, blk.y * H, blk.w * W, blk.h * H
        if y < ch:
            col = tuple(c / 255 for c in blk.color)
            ax[1, 0].add_patch(Rectangle((x, y), w, h, fill=False, edgecolor=col, lw=1.6))
            n_shown += 1
    ax[1, 0].set_title(f"③ block_color / text_color — {n_shown} OCR text blocks "
                       "(matched + colour-scored)", fontsize=12, loc="left")

    # 4 — edge_ssim: Sobel edge map
    ax[1, 1].imshow(edges, cmap="gray_r")
    ax[1, 1].set_title("④ edge_ssim — Sobel edge map (typography + shape, "
                       "background-robust)", fontsize=12, loc="left")

    for a in ax.flat:
        a.set_xticks([]); a.set_yticks([])
    fig.suptitle("What the grader sees — five signals on one page "
                 "(+ block_ssim = within-block SSIM on each matched block in ③)",
                 fontsize=14, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.985))
    fig.savefig("docs/figures/grader_anatomy.png", dpi=110)
    plt.close(fig)
    print("wrote docs/figures/grader_anatomy.png")


if __name__ == "__main__":
    main()
