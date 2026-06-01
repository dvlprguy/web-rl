"""Grade every ladder rung against the truth → the monotonicity curve.

Renders the truth once, then each rung, and grades with the LIVE offline grader
(DEFAULT_WEIGHTS — structure + colour + the region SSIM/edge dims). Prints reward +
per-dimension means so we can see which dimension carries the signal and whether the
reward falls monotonically as the rung degrades. Intermediates live in temp dirs and
are deleted.

    venv/bin/python ladder_grade.py                                  # content ladder
    venv/bin/python ladder_grade.py --name eval-apple-easy-color        # hue ladder
    venv/bin/python ladder_grade.py --name eval-apple-easy-light        # lightness ladder
"""

import argparse
import statistics
import tempfile
from pathlib import Path

from pipeline.grader import GraderConfig, grade_site
from pipeline.render import capture_site

ap = argparse.ArgumentParser()
ap.add_argument("--truth", default="website-rl-eval-harbor/eval-apple-easy/solution/site")
ap.add_argument("--ladder", default="ladder")
ap.add_argument("--name", default="eval-apple-easy")
ap.add_argument("--levels", default="100,90,80,60,50,25,10,5,0")
args = ap.parse_args()

cfg = GraderConfig()  # DEFAULT_WEIGHTS — the live grader's active dims
levels = [int(x) for x in args.levels.split(",")]
truth = Path(args.truth)
DIMS = tuple(sorted(cfg.weights))  # show every active dimension, whatever it is


def render(site_dir, dst):
    capture_site(str(Path(site_dir).resolve()), dst, extract_boxes=True)


with tempfile.TemporaryDirectory() as ref_d:
    render(truth, ref_d)  # reference rendered once

    print(f"{'rung':>6s}  {'reward':>7s}  " + "  ".join(f"{d:>11s}" for d in DIMS))
    print("-" * (17 + 13 * len(DIMS)))
    prev = None
    for L in levels:
        site = truth if L == 100 else Path(args.ladder) / f"{args.name}-{L}"
        if not Path(site).exists():
            continue
        with tempfile.TemporaryDirectory() as cand_d:
            render(site, cand_d)
            res = grade_site(ref_d, cand_d, cfg=cfg)
        # mean of each dimension across pages that have it
        dim_means = {}
        for d in DIMS:
            vals = [p["dimensions"][d] for p in res.pages.values()
                    if "dimensions" in p and d in p["dimensions"]]
            dim_means[d] = statistics.mean(vals) if vals else float("nan")
        arrow = "" if prev is None else ("  ↓" if res.reward < prev + 1e-9 else "  ↑ NON-MONO")
        print(f"{L:6d}  {res.reward:7.4f}  "
              + "  ".join(f"{dim_means[d]:11.4f}" for d in DIMS) + arrow)
        prev = res.reward
