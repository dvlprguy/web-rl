"""Task gallery — a grid of all 21 tasks' home pages (top viewport), so the
distribution/variety is visible at a glance. Writes docs/figures/task_gallery.png.

    venv/bin/python scripts/make_gallery.py
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image  # noqa: E402

HARBOR = Path("website-rl-eval-harbor")
TIER_ORDER = {"easy": 0, "medium": 1, "hard": 2}
TIER_COLOR = {"easy": "#4c9f70", "medium": "#e0a83b", "hard": "#c0504d"}
VIEW_H = 820  # crop to the first viewport so thumbnails are comparable


def first_page(task):
    refs = sorted((HARBOR / task / "tests/reference").glob("*.png"))
    home = [r for r in refs if r.stem == "home"]
    return (home or refs)[0] if refs else None


def main():
    with open("results/per_task.csv") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: (TIER_ORDER[r["tier"]], r["seed"]))

    cols = 3
    n = len(rows)
    nrows = (n + cols - 1) // cols
    fig, axes = plt.subplots(nrows, cols, figsize=(cols * 4.0, nrows * 2.9))
    axes = axes.flatten()
    for ax, r in zip(axes, rows):
        p = first_page(r["task"])
        if p:
            im = Image.open(p).convert("RGB")
            im = im.crop((0, 0, im.width, min(VIEW_H, im.height)))
            ax.imshow(im)
        ax.set_title(f"{r['seed']}  ·  {r['tier']}  ·  {float(r['reward_mean']):.2f}",
                     fontsize=10, color=TIER_COLOR[r["tier"]], fontweight="bold")
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_edgecolor(TIER_COLOR[r["tier"]]); s.set_linewidth(2.5)
    for ax in axes[n:]:
        ax.axis("off")
    fig.suptitle("The 21-task fleet — one home page each (seed · tier · mean reward)",
                 fontsize=14, y=0.997)
    fig.tight_layout(rect=(0, 0, 1, 0.99))
    fig.savefig("docs/figures/task_gallery.png", dpi=110)
    plt.close(fig)
    print(f"wrote docs/figures/task_gallery.png ({n} tasks)")


if __name__ == "__main__":
    main()
