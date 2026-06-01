"""Generate the visual-report figures from results/ into docs/figures/.

    venv/bin/python scripts/make_figures.py

Produces:
    reward_by_difficulty.png   per-task reward by tier (strip + tier-mean) — monotone dial
    dimensions_by_tier.png     per-dimension mean by tier — what drives/limits the reward
    per_task_reward.png        all 21 tasks sorted, tier-coloured, ±std — the distribution
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

DIMS = ["structure", "block_color", "block_ssim", "edge_ssim", "text_color"]
TIER_ORDER = ["easy", "medium", "hard"]
TIER_COLOR = {"easy": "#4c9f70", "medium": "#e0a83b", "hard": "#c0504d"}
FIG = Path("docs/figures")


def load(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def reward_by_difficulty(per_task):
    fig, ax = plt.subplots(figsize=(6.2, 4.4))
    for i, tier in enumerate(TIER_ORDER):
        ys = [float(r["reward_mean"]) for r in per_task if r["tier"] == tier]
        xs = [i + (j - len(ys) / 2) * 0.045 for j in range(len(ys))]
        ax.scatter(xs, ys, s=70, color=TIER_COLOR[tier], alpha=0.85,
                   edgecolor="white", zorder=3, label=f"{tier} (n={len(ys)})")
        m = sum(ys) / len(ys)
        ax.hlines(m, i - 0.22, i + 0.22, color=TIER_COLOR[tier], lw=3, zorder=4)
        ax.text(i, m + 0.006, f"{m:.3f}", ha="center", fontsize=10, fontweight="bold")
    ax.set_xticks(range(3)); ax.set_xticklabels([t.upper() for t in TIER_ORDER])
    ax.set_ylabel("mean reward (per task, 3 trials)")
    ax.set_title("Reward vs. difficulty — the dial is monotone (easy > medium > hard)")
    ax.grid(axis="y", alpha=0.25); ax.set_ylim(0.70, 0.84)
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout(); fig.savefig(FIG / "reward_by_difficulty.png", dpi=140)
    plt.close(fig)


def dimensions_by_tier(per_task):
    means = {tier: {d: [] for d in DIMS} for tier in TIER_ORDER}
    for r in per_task:
        for d in DIMS:
            if r[d]:
                means[r["tier"]][d].append(float(r[d]))
    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    x = range(len(DIMS)); w = 0.26
    for k, tier in enumerate(TIER_ORDER):
        vals = [sum(means[tier][d]) / len(means[tier][d]) for d in DIMS]
        ax.bar([i + (k - 1) * w for i in x], vals, w, color=TIER_COLOR[tier],
               label=tier, edgecolor="white")
    ax.set_xticks(list(x)); ax.set_xticklabels(DIMS, rotation=15)
    ax.set_ylabel("mean dimension score"); ax.set_ylim(0, 1.0)
    ax.set_title("Per-dimension score by tier — edge_ssim drives difficulty, "
                 "block_ssim is the floor")
    ax.legend(frameon=False); ax.grid(axis="y", alpha=0.25)
    fig.tight_layout(); fig.savefig(FIG / "dimensions_by_tier.png", dpi=140)
    plt.close(fig)


def per_task_reward(per_task):
    rows = sorted(per_task, key=lambda r: float(r["reward_mean"]))
    fig, ax = plt.subplots(figsize=(7.2, 7.0))
    ys = range(len(rows))
    ax.barh(list(ys), [float(r["reward_mean"]) for r in rows],
            xerr=[float(r["reward_std"]) for r in rows],
            color=[TIER_COLOR[r["tier"]] for r in rows],
            edgecolor="white", error_kw={"ecolor": "#444", "lw": 1})
    ax.set_yticks(list(ys)); ax.set_yticklabels([r["seed"] for r in rows], fontsize=9)
    ax.set_xlabel("mean reward ± std (3 trials)"); ax.set_xlim(0.60, 0.86)
    ax.set_title("All 21 fruit tasks, sorted by reward (colour = difficulty tier)")
    ax.grid(axis="x", alpha=0.25)
    handles = [plt.Rectangle((0, 0), 1, 1, color=TIER_COLOR[t]) for t in TIER_ORDER]
    ax.legend(handles, TIER_ORDER, frameon=False, loc="lower right")
    fig.tight_layout(); fig.savefig(FIG / "per_task_reward.png", dpi=140)
    plt.close(fig)


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    per_task = load("results/per_task.csv")
    reward_by_difficulty(per_task)
    dimensions_by_tier(per_task)
    per_task_reward(per_task)
    print(f"wrote 3 figures to {FIG}/")


if __name__ == "__main__":
    main()
