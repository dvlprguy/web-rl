"""Worked-example figures: truth vs. agent render, side by side, with the page's
grader scores. The agent's saved HTML is re-rendered IN THE TASK'S OWN font image
(the same one that produced the reference), so the comparison is apples-to-apples.

    venv/bin/python scripts/make_examples.py

Needs Docker (the per-task env image `eval-<seed>-<tier>-env:build`, built by
build_task.sh). Writes docs/figures/example_<seed>_<page>.png.
"""

from __future__ import annotations

import glob
import json
import subprocess
import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image  # noqa: E402

DIMS = ["structure", "block_color", "block_ssim", "edge_ssim", "text_color"]

# (task, page, caption) — chosen to span the reward range across tiers.
EXAMPLES = [
    ("eval-pear-easy", "home", "Strong replica · easy · 0.81"),
    ("eval-peach-medium", "home", "Strong replica · medium · 0.80"),
    ("eval-raspberry-hard", "home", "Strong replica · hard · 0.78"),
    ("eval-apricot-easy", "home", "Weaker replica · easy · 0.73"),
    ("eval-mango-medium", "home", "edge_ssim failure (illustration/shape miss) · medium · 0.74"),
    ("eval-kiwi-hard", "home", "Weakest replica in the fleet · hard · 0.71"),
]


def latest_job(task):
    return sorted(glob.glob(f"website-rl-eval-harbor/{task}/jobs/*/"))[-1]


def median_trial(job):
    res = json.loads(Path(job + "result.json").read_text())
    rmap = {}
    for ev in res["stats"]["evals"].values():
        for v, trials in ev["reward_stats"]["reward"].items():
            for t in trials:
                rmap[t] = float(v)
    items = sorted(rmap.items(), key=lambda x: x[1])
    return items[len(items) // 2]  # (trial_name, reward) — the median attempt


def render_agent(task, trial_name, outdir):
    site = str(Path(f"{latest_job(task)}{trial_name}/artifacts/app/site").resolve())
    subprocess.run(
        ["docker", "run", "--rm", "-v", f"{site}:/in:ro", "-v", f"{outdir}:/out",
         f"{task}-env:build", "python3", "-c",
         "from pipeline.render import capture_site; capture_site('/in','/out',extract_boxes=False)"],
        check=True, capture_output=True,
    )


def make(task, page, caption):
    job = latest_job(task)
    trial, reward = median_trial(job)
    rep = json.loads(Path(f"{job}{trial}/verifier/grade_report.json").read_text())
    pg = rep["pages"].get(page, {})
    dims = pg.get("dimensions", {})
    combined = pg.get("combined", float("nan"))

    truth = Image.open(f"website-rl-eval-harbor/{task}/tests/reference/{page}.png").convert("RGB")
    with tempfile.TemporaryDirectory() as out:
        render_agent(task, trial, out)
        agent = Image.open(f"{out}/{page}.png").convert("RGB")

        fig, (a0, a1) = plt.subplots(1, 2, figsize=(11, 7.2))
        a0.imshow(truth); a0.set_title("TARGET (reference)", fontsize=11); a0.axis("off")
        a1.imshow(agent); a1.set_title("AGENT (Opus 4.7 replica)", fontsize=11); a1.axis("off")
        seed = task.split("-")[1]
        dimstr = "   ".join(f"{d}={dims[d]:.2f}" for d in DIMS if d in dims)
        fig.suptitle(f"{caption}\n{seed} · {page}.html · page reward = {combined:.3f}   "
                     f"(task mean {reward:.3f})\n{dimstr}", fontsize=10)
        fig.tight_layout(rect=(0, 0, 1, 0.93))
        fig.savefig(f"docs/figures/example_{seed}_{page}.png", dpi=120)
        plt.close(fig)
        print(f"  wrote docs/figures/example_{seed}_{page}.png  (reward {combined:.3f})")


def main():
    Path("docs/figures").mkdir(parents=True, exist_ok=True)
    for task, page, caption in EXAMPLES:
        try:
            make(task, page, caption)
        except Exception as e:
            print(f"  FAILED {task}/{page}: {e}")


if __name__ == "__main__":
    main()
