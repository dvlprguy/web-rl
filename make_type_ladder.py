"""Ladder 3 — typography. Holds STRUCTURE and COLOUR fixed, degrades only the FONT.

This is the ladder for the two dims nothing else exercises: ``block_ssim``
(within-block render fidelity — font weight/family/fill) and ``edge_ssim`` (global
Sobel-edge / glyph-shape SSIM). The HTML is copied byte-for-byte and no colour token
is touched; we only append a ``*{...}!important`` override to style.css that mangles
the font. Right boxes, right colours, WRONG type.

Two modes (parallels make_color_ladder's hue/lightness split):
  --mode weight   font-weight 400→900 only, family preserved. The clean isolation
                  test — weight barely reflows, so STRUCTURE should stay ~flat and
                  the movement is pure glyph thickness (block_ssim / edge_ssim).
  --mode family   swap the serif body toward progressively more dissimilar families
                  (diff-serif → humanist sans → grotesque sans → monospace), with a
                  weight drift on top. The wide-RANGE test — big glyph-shape change,
                  so edge_ssim should move hard. Family swaps reflow text, so expect
                  some STRUCTURE leakage; the scorecard MEASURES it rather than
                  pretending it's zero (font/layout coupling is a real finding).

Suffix = type fidelity RETAINED %.  100 = identical, 0 = maximally wrong
(weight 900, or monospace).

    venv/bin/python make_type_ladder.py --mode weight
    venv/bin/python make_type_ladder.py --mode family
"""

import argparse
import shutil
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--truth", default="website-rl-eval-harbor/eval-apple-easy/solution/site")
ap.add_argument("--out", default="ladder")
ap.add_argument("--mode", choices=("weight", "family"), default="weight")
ap.add_argument("--name", default=None, help="rung-dir prefix (default: eval-apple-easy-type | -family)")
ap.add_argument("--levels", default="100,90,80,60,50,25,10,5,0")
args = ap.parse_args()

# Default rung name reflects the mode; keep '-type' for the weight isolation test.
name = args.name or ("eval-apple-easy-type" if args.mode == "weight" else "eval-apple-easy-family")

truth = Path(args.truth)
levels = [int(x) for x in args.levels.split(",")]

# Family tiers ordered by DISTANCE from the truth's serif body, closest → furthest.
# amount∈(0,1] indexes into these; amount→1 lands on monospace (maximally wrong).
_FAMILY_TIERS = [
    "Georgia, 'Times New Roman', serif",            # 1: different serif metrics (mild)
    "'Trebuchet MS', Verdana, Helvetica, sans-serif",  # 2: humanist sans
    "Arial, Helvetica, sans-serif",                  # 3: grotesque sans
    "'Courier New', Courier, monospace",             # 4: monospace (max shape change)
]


def _family_for(amount: float) -> str:
    """Pick a family tier for an amount in (0, 1]. Monotone: more amount → further."""
    idx = min(len(_FAMILY_TIERS) - 1, int(amount * len(_FAMILY_TIERS)))
    return _FAMILY_TIERS[idx]


def _override_rule(amount: float, mode: str) -> str:
    """The `* { ... !important }` block to append to style.css for this rung.

    Both modes ramp letter-spacing CONTINUOUSLY (the renderer honours it at any
    value, unlike font-weight, which the OS quantises to regular/bold — that
    quantisation otherwise collapses the curve into 2-3 plateaus). Weight/family
    supply the magnitude; letter-spacing supplies the smoothness."""
    if amount == 0:
        return ""  # identical rung — no override
    if mode == "weight":
        weight = round(400 + amount * 500)  # 400 → 900 (quantised to regular/bold)
        ls = amount * 0.16  # em — continuous, the smoothing knob
        decls = f"font-weight:{weight} !important; letter-spacing:{ls:.4f}em !important;"
    else:  # family
        weight = round(400 + amount * 400)  # 400 → 800, drift within tier
        ls = amount * 0.10
        fam = _family_for(amount)
        decls = (
            f"font-family:{fam} !important; font-weight:{weight} !important; "
            f"letter-spacing:{ls:.4f}em !important;"
        )
    return f"\n/* TYPE-LADDER ({mode}) override */\n*{{ {decls} }}\n"


print(f"truth: {truth}   mode: {args.mode}   type-fidelity levels: {levels}")
css = truth / "style.css"
for L in levels:
    amount = (100 - L) / 100  # 0 at L=100 (identical) → 1 at L=0 (maximally wrong)
    d = Path(args.out) / f"{name}-{L}"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    # HTML copied verbatim — structure input is byte-identical; any structure-metric
    # movement is pure rendered reflow, which is the leakage we want to measure.
    for f in truth.glob("*.html"):
        shutil.copy(f, d / f.name)
    if css.exists():
        css_text = css.read_text()
        override = _override_rule(amount, args.mode)
        # The truth's style.css ends with stray HTML junk (</style></body></html>).
        # A CSS parser drops any rule that FOLLOWS </style>, so insert the override
        # before it (valid-CSS territory) rather than at EOF.
        cut = css_text.find("</style>")
        if cut != -1:
            css_text = css_text[:cut] + override + css_text[cut:]
        else:
            css_text += override
        (d / "style.css").write_text(css_text)
    if args.mode == "weight":
        label = f"weight {round(400 + amount * 500)}"
    else:
        label = f"{_family_for(amount).split(',')[0]:<16s} w{round(400 + amount * 400)}" if amount else "(identical)"
    print(f"  {name}-{L:<3d}  {label}")
print(f"\nwrote {len(levels)} rungs → {args.out}/{name}-*")
