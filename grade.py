"""Grade one site replica against a target — raw HTML/CSS in, score out.

Both inputs are plain directories of `*.html` + `style.css` (no pre-rendering
needed). This renders each with the SAME path the Harbor verifier uses, runs the
grader, prints the score, and deletes every intermediate (the screenshots + box
sidecars live in temp dirs that are removed on exit — nothing persists).

    venv/bin/python grade.py <target_dir> <candidate_dir>

Grading is fully offline (structure + colour + region SSIM/edge dims); no API key.

Example (target = reference source, candidate = an agent's replica):
    venv/bin/python grade.py \\
        website-rl-eval-harbor/eval-apple-easy/.build/site \\
        website-rl-eval-harbor/eval-apple-easy/jobs/2026-05-31__23-06-35/eval-apple-easy__sCKiiro/artifacts/app/site
"""

import argparse
import tempfile
from pathlib import Path

from pipeline.grader import GraderConfig, grade_site
from pipeline.render import capture_site

ap = argparse.ArgumentParser(description="Grade a candidate site against a target.")
ap.add_argument("target", help="dir of reference *.html + style.css")
ap.add_argument("candidate", help="dir of candidate *.html + style.css")
args = ap.parse_args()

# Mirror the Harbor verifier exactly: the default active dims + weights
# (pipeline.grader.DEFAULT_WEIGHTS), fully offline (VLM/perceptual dropped). One
# source of truth, so local grading and the in-container reward never drift.
cfg = GraderConfig()

# Render both sides to throwaway temp dirs (auto-deleted on block exit), grade,
# done. Nothing is written outside these temp dirs.
with tempfile.TemporaryDirectory() as ref_d, tempfile.TemporaryDirectory() as cand_d:
    capture_site(str(Path(args.target).resolve()), ref_d, extract_boxes=True)
    capture_site(str(Path(args.candidate).resolve()), cand_d, extract_boxes=True)
    res = grade_site(ref_d, cand_d, cfg=cfg)

for stem, p in sorted(res.pages.items()):
    print(f"  {stem:12s} {p['combined']:.3f}  {p.get('dimensions', {})}")
print(f"REWARD = {res.reward:.4f}")
