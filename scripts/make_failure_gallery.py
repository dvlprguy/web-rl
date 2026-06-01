"""Failure gallery — zoomed truth-vs-agent crops of the patterns the model
struggles with, one row per failure mode. Writes docs/figures/failure_gallery.png.
The detailed explanation lives in the prose that embeds this figure (evaluation.md §5).

Agent renders come from _render_out/<task>/ (rendered in-image; gitignored scratch).
    venv/bin/python scripts/make_failure_gallery.py
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image  # noqa: E402

# (task, crop box (x0,y0,x1,y1), "seed — failure mode · dimension")
FAILURES = [
    ("eval-apricot-easy", (0, 0, 1280, 470),
     "apricot — wrong font weight & spacing  ·  block_ssim"),
    ("eval-kiwi-hard", (0, 0, 1280, 650),
     "kiwi — dense data / charts diverge  ·  edge_ssim"),
    ("eval-blueberry-hard", (0, 0, 1280, 540),
     "blueberry — palette drift  ·  block_color / text_color"),
]


def _label(ax, text):
    ax.text(0.012, 0.975, text, transform=ax.transAxes, fontsize=10, fontweight="bold",
            va="top", ha="left", color="white",
            bbox=dict(boxstyle="round,pad=0.25", fc="#222", ec="none", alpha=0.7))


def main():
    n = len(FAILURES)
    fig, axes = plt.subplots(n, 2, figsize=(12, 4.4 * n))
    for row, (task, box, title) in enumerate(FAILURES):
        truth = Image.open(f"website-rl-eval-harbor/{task}/tests/reference/home.png").convert("RGB").crop(box)
        agent = Image.open(f"_render_out/{task}/home.png").convert("RGB").crop(box)
        a0, a1 = axes[row]
        a0.imshow(truth); _label(a0, "TARGET")
        a1.imshow(agent); _label(a1, "AGENT")
        a0.set_title(f"▸ {title}", loc="left", fontsize=12.5, fontweight="bold",
                     color="#b03a2e", pad=8)
        for a in (a0, a1):
            a.set_xticks([]); a.set_yticks([])
    fig.suptitle("What the model struggles with — zoomed target vs. agent (Opus 4.7)",
                 fontsize=15, y=1.0)
    fig.tight_layout(rect=(0, 0, 1, 0.985), h_pad=3.5)
    fig.savefig("docs/figures/failure_gallery.png", dpi=120)
    plt.close(fig)
    print("wrote docs/figures/failure_gallery.png")


if __name__ == "__main__":
    main()
