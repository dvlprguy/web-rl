"""Degradation-ladder curves — the visual proof that the reward is monotone with
true fidelity (the grader trust gate). Writes docs/figures/ladder_monotonicity.png.

The numbers below are the measured ladder results recorded in decisions.md (D9/D12)
and findings.md (F1). Regenerate the raw values end-to-end with:
    venv/bin/python make_ladder.py        && venv/bin/python ladder_grade.py
    venv/bin/python make_color_ladder.py --mode lightness && ladder_grade.py --name eval-apple-easy-light
    venv/bin/python make_type_ladder.py  --mode family    && ladder_grade.py --name eval-apple-easy-family

    venv/bin/python scripts/make_ladder_plot.py
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# x = % of the perfect site RETAINED (100 = untouched, 0 = maximally corrupted on that axis)
RETAIN = [100, 90, 80, 60, 50, 25, 10, 5, 0]

LADDERS = {
    "content drop (remove elements)": {
        "y": [1.0000, 0.9042, 0.8424, 0.7533, 0.6951, 0.5134, 0.0580, 0.0463, 0.0039],
        "c": "#3b6ea5",
    },
    "colour wrong (lightness inverted)": {
        "y": [1.0000, 0.9589, 0.8970, 0.7715, 0.6663, 0.5041, 0.4516, 0.4500, 0.4221],
        "c": "#c0504d",
    },
    "typography wrong (fonts mangled)": {
        "y": [1.0000, 0.8974, 0.8935, 0.8169, 0.7936, 0.8057, 0.8003, 0.8031, 0.7894],
        "c": "#4c9f70",
    },
}


def main():
    fig, ax = plt.subplots(figsize=(7.6, 4.8))
    for label, d in LADDERS.items():
        ax.plot(RETAIN, d["y"], "-o", color=d["c"], lw=2, ms=5, label=label)
    ax.set_xlabel("% of the perfect replica retained on that axis  (100 → 0 = more damage)")
    ax.set_ylabel("grader reward")
    ax.set_title("Degradation ladders — reward falls monotonically as a perfect\n"
                 "copy is damaged (the trust gate: higher reward ⇒ closer replica)")
    ax.set_xlim(102, -2)  # left = perfect, right = worst
    ax.set_ylim(-0.03, 1.03)
    ax.grid(alpha=0.25)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    ax.annotate("honest ceiling = 1.0\n(exact copy)", xy=(100, 1.0), xytext=(86, 0.55),
                fontsize=8, arrowprops=dict(arrowstyle="->", color="#888"))
    ax.annotate("honest floor ≈ 0\n(empty page)", xy=(0, 0.004), xytext=(22, 0.16),
                fontsize=8, arrowprops=dict(arrowstyle="->", color="#888"))
    fig.tight_layout()
    fig.savefig("docs/figures/ladder_monotonicity.png", dpi=140)
    plt.close(fig)
    print("wrote docs/figures/ladder_monotonicity.png")


if __name__ == "__main__":
    main()
