"""One-off: show what `structure_score` actually computes, on a REAL trial.

Renders the agent's contact.html (from a real docker run) the same way the
verifier does, extracts its element boxes, and breaks structure_score into its
four sub-signals against the reference boxes. Throwaway demo, not pipeline code.
"""

import json
import tempfile
from pathlib import Path

import numpy as np

from pipeline.metrics import structure
from pipeline.render import capture_page

TRIAL = Path(
    "website-rl-eval-harbor/eval-quartz-99/jobs/docker-run/eval-quartz-99__NniMUSb"
)
REF = Path("website-rl-eval-harbor/eval-quartz-99/tests/reference")
PAGE = "contact"

ref_boxes = json.loads((REF / f"{PAGE}.boxes.json").read_text())

# Render the agent's page exactly like the verifier (full_page, extract boxes).
with tempfile.TemporaryDirectory() as d:
    out = Path(d) / f"{PAGE}.png"
    html = TRIAL / "artifacts/app/site" / f"{PAGE}.html"
    capture_page(html, out, extract_boxes=True)
    cand_boxes = json.loads(out.with_suffix(".boxes.json").read_text())


def breakdown(ref, cand):
    n_ref, n_cand = len(ref), len(cand)
    count = structure._ratio(n_ref, n_cand)
    tr = sum(b.get("text", 0) for b in ref)
    tc = sum(b.get("text", 0) for b in cand)
    text = structure._ratio(tr, tc)
    size = float(np.minimum(structure._size_hist(ref), structure._size_hist(cand)).sum())
    grid = structure._map_similarity(structure._edge_map(ref), structure._edge_map(cand))
    total = structure.structure_score(ref, cand)
    return n_ref, n_cand, tr, tc, count, text, size, grid, total


nr, nc, tr, tc, count, text, size, grid, total = breakdown(ref_boxes, cand_boxes)

print(f"PAGE: {PAGE}  (real Opus-4.7 trial NniMUSb)")
print(f"  element count   ref={nr:4d}  cand={nc:4d}   count_sim = {count:.4f}  (w .30)")
print(f"  text mass(chars)ref={tr:4d}  cand={tc:4d}   text_sim  = {text:.4f}  (w .15)")
print(f"  size histogram                       size_sim  = {size:.4f}  (w .15)")
print(f"  edge-density grid                    grid_sim  = {grid:.4f}  (w .40)")
print(f"  --------------------------------------------------")
print(f"  structure_score                      = {total:.4f}")
print(f"  (grade_report.json recorded          = 0.6914)")
