"""Per-dimension VLM rubric breakdown for a target vs candidate site.

The grader only keeps VLM's averaged scalar. This shows the five raw 0–4 axes
(layout, color, typography, spacing, content) per page — and runs the WHOLE thing
N times so you can see how much the judge wobbles between identical calls (the
variance is the case for/against keeping it). Renders to temp dirs, cleans up.

    venv/bin/python vlm_breakdown.py <target_dir> <candidate_dir> [--runs 2]
"""

import argparse
import statistics
import tempfile
from pathlib import Path

from pipeline.metrics import imageutil, vlm  # noqa: F401  (imageutil keeps deps warm)
from pipeline.metrics.vlm import vlm_rubric
from pipeline.render import capture_site

ap = argparse.ArgumentParser()
ap.add_argument("target")
ap.add_argument("candidate")
ap.add_argument("--runs", type=int, default=2, help="repeat calls to gauge variance")
args = ap.parse_args()

DIMS = ("layout", "color", "typography", "spacing", "content")

with tempfile.TemporaryDirectory() as ref_d, tempfile.TemporaryDirectory() as cand_d:
    ref = capture_site(str(Path(args.target).resolve()), ref_d, extract_boxes=False)
    cand = capture_site(str(Path(args.candidate).resolve()), cand_d, extract_boxes=False)
    pages = sorted(set(ref) & set(cand))

    # page -> dim -> list of scores across runs
    allruns: dict[str, dict[str, list[float]]] = {p: {d: [] for d in DIMS} for p in pages}
    for r in range(args.runs):
        for p in pages:
            sub = vlm_rubric(ref[p], cand[p])
            for d in DIMS:
                if d in sub:
                    allruns[p][d].append(sub[d])

hdr = "page".ljust(12) + "".join(d[:9].ljust(11) for d in DIMS) + "mean"
print(hdr)
print("-" * len(hdr))
for p in pages:
    cells = ""
    means = []
    for d in DIMS:
        vals = allruns[p][d]
        if not vals:
            cells += "—".ljust(11)
            continue
        m = statistics.mean(vals)
        means.append(m)
        spread = f"±{(max(vals) - min(vals)):.0f}" if len(vals) > 1 else ""
        cells += f"{m:.1f}/4{spread}".ljust(11)
    mean_str = f"{statistics.mean(means) / 4:.3f}" if means else "—"
    print(p.ljust(12) + cells + mean_str)

# Per-dimension variance across all pages*runs — how noisy is each axis?
print("\nper-dimension spread (across all pages & runs):")
for d in DIMS:
    flat = [v for p in pages for v in allruns[p][d]]
    rng = f"{min(flat):.0f}–{max(flat):.0f}" if flat else "—"
    sd = statistics.pstdev(flat) if len(flat) > 1 else 0.0
    print(f"  {d:11s} range {rng}   stdev {sd:.2f}")
