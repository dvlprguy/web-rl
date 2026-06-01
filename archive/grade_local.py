"""Run the grader locally — same code path as the Harbor verifier (tests/test.sh).

Renders a candidate site (*.html + style.css) the way the verifier does, then
grades it against a task's bundled tests/reference. Playwright runs on the laptop;
no Docker/Modal needed.

    venv/bin/python grade_local.py <task_dir> <candidate_site_dir>

Examples (eval-seed-67):
    # oracle ceiling — grade the reference source against itself (≈1.0)
    venv/bin/python grade_local.py \\
        website-rl-eval-harbor/eval-seed-67 \\
        website-rl-eval-harbor/eval-seed-67/.build/site

    # a real agent trial's output
    venv/bin/python grade_local.py \\
        website-rl-eval-harbor/eval-seed-67 \\
        website-rl-eval-harbor/eval-seed-67/jobs/2026-05-31__23-06-35/eval-seed-67__sCKiiro/artifacts/app/site
"""

import sys
import tempfile
from pathlib import Path

from pipeline.grader import GraderConfig, grade_site
from pipeline.render import capture_site

task_dir = Path(sys.argv[1]).resolve()
cand_site = Path(sys.argv[2]).resolve()
reference = task_dir / "tests" / "reference"

# Mirror tests/test.sh: color + structure + VLM rubric (perceptual dropped — D6).
# VLM needs ANTHROPIC_API_KEY in the env + litellm (both present locally).
cfg = GraderConfig(weights={"color": 0.6, "structure": 1.0, "vlm": 0.6})

with tempfile.TemporaryDirectory() as d:
    capture_site(str(cand_site), d, extract_boxes=True)
    res = grade_site(str(reference), d, cfg=cfg)

for stem, p in sorted(res.pages.items()):
    print(f"  {stem:12s} {p['combined']:.3f}  {p.get('dimensions', {})}")
print(f"REWARD = {res.reward:.4f}")
