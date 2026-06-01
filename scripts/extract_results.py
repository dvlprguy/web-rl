"""Extract the fruit-fleet evaluation results into committed data files.

Reads each task's latest Harbor job (the raw job dirs are large and git-ignored) and
writes compact, reviewable artifacts under results/:

    results/per_trial.csv   one row per (task, trial): reward + per-dimension means
    results/per_task.csv    one row per task: reward mean/std/min/max + per-dim means
    results/summary.json    per-tier and fleet aggregates

The per-dimension values are the mean over a trial's pages, read from each trial's
verifier/grade_report.json (the grader's own output). Run from the repo root:

    venv/bin/python scripts/extract_results.py
"""

from __future__ import annotations

import csv
import glob
import json
import statistics
from pathlib import Path

HARBOR = Path("website-rl-eval-harbor")
DIMS = ["structure", "block_color", "block_ssim", "edge_ssim", "text_color"]
TIERS = {
    "easy": ["apple", "grape", "lemon", "pear", "apricot", "guava"],
    "medium": ["banana", "peach", "plum", "lime", "mango", "papaya", "coconut"],
    "hard": ["cherry", "melon", "fig", "kiwi", "pomegranate", "pineapple",
             "raspberry", "blueberry"],
}


def latest_job(task_dir: Path) -> Path | None:
    jobs = sorted(task_dir.glob("jobs/*/"))
    return jobs[-1] if jobs else None


def trial_rows(task: str, tier: str, seed: str) -> list[dict]:
    """One row per completed trial: reward + per-dimension mean over its pages."""
    job = latest_job(HARBOR / task)
    if job is None:
        return []
    rows = []
    for report in sorted(job.glob(f"{task}__*/verifier/grade_report.json")):
        rep = json.loads(report.read_text())
        trial_id = report.parts[-3].split("__")[-1]
        per_dim = {d: [] for d in DIMS}
        for page in rep.get("pages", {}).values():
            for d, v in page.get("dimensions", {}).items():
                if d in per_dim:
                    per_dim[d].append(v)
        row = {"task": task, "seed": seed, "tier": tier, "trial": trial_id,
               "reward": round(rep["reward"], 4)}
        for d in DIMS:
            row[d] = round(statistics.mean(per_dim[d]), 4) if per_dim[d] else ""
        rows.append(row)
    return rows


def main() -> None:
    all_trials: list[dict] = []
    per_task: list[dict] = []
    for tier, seeds in TIERS.items():
        for seed in seeds:
            task = f"eval-{seed}-{tier}"
            rows = trial_rows(task, tier, seed)
            if not rows:
                print(f"  WARNING: no trials for {task}")
                continue
            all_trials.extend(rows)
            rewards = [r["reward"] for r in rows]
            agg = {"task": task, "seed": seed, "tier": tier, "n_trials": len(rows),
                   "reward_mean": round(statistics.mean(rewards), 4),
                   "reward_std": round(statistics.pstdev(rewards), 4) if len(rewards) > 1 else 0.0,
                   "reward_min": min(rewards), "reward_max": max(rewards)}
            for d in DIMS:
                vals = [r[d] for r in rows if r[d] != ""]
                agg[d] = round(statistics.mean(vals), 4) if vals else ""
            per_task.append(agg)

    Path("results").mkdir(exist_ok=True)
    # per_trial.csv
    with open("results/per_trial.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["task", "seed", "tier", "trial", "reward", *DIMS])
        w.writeheader(); w.writerows(all_trials)
    # per_task.csv
    with open("results/per_task.csv", "w", newline="") as f:
        cols = ["task", "seed", "tier", "n_trials", "reward_mean", "reward_std",
                "reward_min", "reward_max", *DIMS]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader(); w.writerows(per_task)
    # summary.json
    summary = {"tiers": {}, "fleet": {}}
    for tier in TIERS:
        means = [t["reward_mean"] for t in per_task if t["tier"] == tier]
        dimmeans = {d: [t[d] for t in per_task if t["tier"] == tier and t[d] != ""] for d in DIMS}
        summary["tiers"][tier] = {
            "n_tasks": len(means),
            "reward_mean": round(statistics.mean(means), 4),
            "reward_std": round(statistics.pstdev(means), 4),
            "reward_min": round(min(means), 4), "reward_max": round(max(means), 4),
            **{d: round(statistics.mean(v), 4) for d, v in dimmeans.items() if v},
        }
    allm = [t["reward_mean"] for t in per_task]
    summary["fleet"] = {"n_tasks": len(allm), "n_trials": len(all_trials),
                        "reward_mean": round(statistics.mean(allm), 4),
                        "reward_std": round(statistics.pstdev(allm), 4)}
    Path("results/summary.json").write_text(json.dumps(summary, indent=2))

    print(f"wrote results/per_trial.csv ({len(all_trials)} trials), "
          f"results/per_task.csv ({len(per_task)} tasks), results/summary.json")
    for tier, s in summary["tiers"].items():
        print(f"  {tier:7s} n={s['n_tasks']} reward={s['reward_mean']:.3f}±{s['reward_std']:.3f}")
    print(f"  FLEET   n={summary['fleet']['n_tasks']} reward={summary['fleet']['reward_mean']:.3f}"
          f"±{summary['fleet']['reward_std']:.3f}")


if __name__ == "__main__":
    main()
