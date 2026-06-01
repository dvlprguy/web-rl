"""Ladder 2 — colour-shift. Holds STRUCTURE fixed, degrades only the palette.

Every element stays exactly where it is (identical layout → structure ≈ 1.0); we
just recolour every colour token in style.css + inline styles. This is the test
structure is blind to: right boxes, WRONG colours. It puts the colour dims
(`color`, `text_color`, `block_color`) on trial — do they fall as the palette
drifts, or are they dead weight?

Two modes (D10 — hue alone is gentle on lightness-dominated pages, so the lightness
variant is the real disambiguator for the colour metrics):
  --mode hue        rotate hue by up to 180° (same lightness; the gentle test)
  --mode lightness  lerp each colour toward its inverted lightness (dark-mode-ish;
                    the scheme corruption block_color should catch hard)

Suffix = colour fidelity RETAINED %.  100 = identical, 0 = maximally wrong
(hue +180°, or fully lightness-inverted).

    venv/bin/python make_color_ladder.py --mode hue
    venv/bin/python make_color_ladder.py --mode lightness
"""

import argparse
import colorsys
import re
import shutil
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--truth", default="website-rl-eval-harbor/eval-apple-easy/solution/site")
ap.add_argument("--out", default="ladder")
ap.add_argument("--mode", choices=("hue", "lightness"), default="hue")
ap.add_argument(
    "--target",
    choices=("all", "text", "surface"),
    default="all",
    help="all = every colour token (html+css); text/surface = ONLY the glyph or "
    "surface :root variables, to disentangle text_color from block_color",
)
ap.add_argument("--name", default=None, help="rung-dir prefix (default: eval-apple-easy-color | -light)")
ap.add_argument("--levels", default="100,90,80,60,50,25,10,5,0")
args = ap.parse_args()

# Which :root variables are GLYPH colour vs SURFACE colour (eval-apple-easy's palette).
# block_color reads a region's MEAN colour (background-dominated), text_color reads
# the glyph colour — so recolouring only surfaces should move block_color while
# text_color stays flat, and vice-versa. That's the isolation test.
_TEXT_VARS = ("text", "muted", "primary", "accent")
_SURFACE_VARS = ("bg", "surface", "secondary")

# Default rung name reflects the mode; keep 'color'/'light' for target=all (back-compat
# with D10). Targeted runs get a distinct prefix so they don't clobber the all-token run.
_mode_tag = "color" if args.mode == "hue" else "light"
if args.target == "all":
    name = args.name or f"eval-apple-easy-{_mode_tag}"
else:
    name = args.name or f"eval-apple-easy-{args.target}-{_mode_tag}"

truth = Path(args.truth)
levels = [int(x) for x in args.levels.split(",")]

# A few common CSS named colours → hex, so we rotate those too (others pass through).
_NAMED = {
    "white": "#ffffff", "black": "#000000", "red": "#ff0000", "green": "#008000",
    "blue": "#0000ff", "navy": "#000080", "gray": "#808080", "grey": "#808080",
    "silver": "#c0c0c0", "orange": "#ffa500", "gold": "#ffd700", "teal": "#008080",
    "purple": "#800080", "maroon": "#800000", "olive": "#808000", "lime": "#00ff00",
}


def _recolor(r, g, b, amount, mode):
    """Recolour one sRGB triple. hue: rotate hue by `amount` degrees. lightness:
    lerp lightness toward its inverse by fraction `amount` (1.0 = full invert)."""
    h, lt, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    if mode == "hue":
        h = (h + amount / 360.0) % 1.0
    else:
        lt = (1 - amount) * lt + amount * (1 - lt)
    r2, g2, b2 = colorsys.hls_to_rgb(h, lt, s)
    return f"#{round(r2 * 255):02x}{round(g2 * 255):02x}{round(b2 * 255):02x}"


def shift_colors(text: str, amount: float, mode: str) -> str:
    if amount == 0:
        return text

    def hex_sub(m):
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) == 8:  # #rrggbbaa — recolour rgb, keep alpha
            return _recolor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), amount, mode) + h[6:8]
        return _recolor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), amount, mode)

    text = re.sub(r"#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", hex_sub, text)

    # rgb()/rgba() → recolour, re-emit as rgb()/rgba()
    def rgb_sub2(m):
        r, g, b = (int(x) for x in (m.group(1), m.group(2), m.group(3)))
        a = m.group(4)
        hx = _recolor(r, g, b, amount, mode).lstrip("#")
        nr, ng, nb = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
        return f"rgba({nr},{ng},{nb},{a})" if a is not None else f"rgb({nr},{ng},{nb})"

    text = re.sub(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", rgb_sub2, text
    )

    # whole-word named colours
    def named_sub(m):
        return _recolor(*_hex_rgb(_NAMED[m.group(0).lower()]), amount, mode)

    text = re.sub(r"\b(" + "|".join(_NAMED) + r")\b", named_sub, text)
    return text


def _hex_rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def shift_vars(css_text: str, var_names, amount: float, mode: str) -> str:
    """Recolour ONLY the values of the given `--var:` declarations in :root.

    Everything else (layout, other colours) is left byte-identical, so this isolates
    the glyph palette from the surface palette."""
    if amount == 0:
        return css_text
    pattern = re.compile(
        r"(--(?:" + "|".join(var_names) + r")\s*:\s*)"
        r"(#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\))"
    )
    return pattern.sub(lambda m: m.group(1) + shift_colors(m.group(2), amount, mode), css_text)


# Which variables this run recolours (empty = recolour every token, target=all).
_target_vars = {"text": _TEXT_VARS, "surface": _SURFACE_VARS}.get(args.target)

print(f"truth: {truth}   mode: {args.mode}   target: {args.target}   levels: {levels}")
css = truth / "style.css"
for L in levels:
    frac = (100 - L) / 100  # 0 at L=100 (identical) → 1 at L=0 (maximally wrong)
    amount = frac * 180.0 if args.mode == "hue" else frac
    d = Path(args.out) / f"{name}-{L}"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    if _target_vars is None:
        # target=all: recolour every token across html + css.
        for f in truth.glob("*.html"):
            (d / f.name).write_text(shift_colors(f.read_text(), amount, args.mode))
        if css.exists():
            (d / "style.css").write_text(shift_colors(css.read_text(), amount, args.mode))
    else:
        # targeted: HTML byte-identical, recolour only the chosen :root variables.
        for f in truth.glob("*.html"):
            shutil.copy(f, d / f.name)
        if css.exists():
            (d / "style.css").write_text(shift_vars(css.read_text(), _target_vars, amount, args.mode))
    label = f"hue +{amount:5.1f}°" if args.mode == "hue" else f"lightness {amount:.2f} inv"
    print(f"  {name}-{L:<3d}  {label}")
print(f"\nwrote {len(levels)} rungs → {args.out}/{name}-*")
