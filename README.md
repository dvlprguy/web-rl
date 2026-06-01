# website-replication RL task pipeline

A scalable pipeline that **generates RL environments** ("tasks") for training/evaluating a coding
agent's ability to **replicate a multi-page website design from screenshots** (→ HTML/CSS), and
**grades that replication on a continuous, monotonic reward**. Tasks run on the
[Harbor](https://github.com/) framework and are evaluated against **Claude Code (Opus 4.7)**.

The hard part — and the thing this project is really about — is the **grader**: the reward has to
rise smoothly and *only* when the replica is genuinely more faithful, with no honest-zero gaps and
no way to game it, because a model trains on this signal.

21 generated tasks, all rendered on the shared font pipeline:

![the 21-task fleet](docs/figures/task_gallery.png)

## The research arc (how the grader got here)

1. **Image-similarity graders fail as RL rewards.** Whole-image embeddings, CLIP, pixel-SSIM all
   lack an honest zero (a *stripped* page still scored ~0.73) and have no range in the
   plausible-replica band. Dropped them ([`decisions.md`](decisions.md) D6/D7).
2. **Grade in render-tree + region space.** DOM-box `structure` (honest zero) + per-region colour +
   within-block SSIM + edge SSIM + matched-text colour, combined as a **geometric mean** so no
   channel can be sacrificed (D11).
3. **Prove it before scaling.** Degradation ladders damage a perfect copy in steps; the reward must
   fall monotonically to an honest floor. It does (D9/D12 — the trust gate).
4. **Caught a silent bug:** the reference was rendered in a *different font world* than the agent, so
   a perfect copy was capped at **0.89**. Fixed by rendering both in the same Docker image
   ([`findings.md`](findings.md) F10/F11).
5. **Validated on 21 generated tasks:** reward tracks difficulty, variance is tight, 0 errors — and
   the model's consistent weak spot is within-block font fidelity.

---

## Start here — reading order

1. **This README** (2 min) — what it is, how it fits together.
2. **[`docs/overview.md`](docs/overview.md)** — *how it works.* The architecture in diagrams:
   generator → render → Harbor task → grader. Scannable, not a wall of text.
3. **[`docs/evaluation.md`](docs/evaluation.md)** — *the result.* The visual report: task gallery,
   reward-vs-difficulty, the monotonicity proof, and best→worst agent-vs-target screenshots.
4. **[`docs/tasks.md`](docs/tasks.md)** — the 21 tasks and how to run one.
5. **[`decisions.md`](decisions.md)** (D1–D12) + **[`findings.md`](findings.md)** (F1–F11) — the deep
   reasoning and the experiments behind every choice. Dip in as interested.
6. **The code:** [`pipeline/grader.py`](pipeline/grader.py) + [`pipeline/metrics/`](pipeline/metrics/)
   (the grader), [`pipeline/generate.py`](pipeline/generate.py) (the site generator),
   [`build_task.sh`](build_task.sh) (the packager).

---

## Deliverables (what to look at)

1. **The recipe / pipeline code** — [`pipeline/`](pipeline/) + [`build_task.sh`](build_task.sh).
   Generate a site → render a reference → package a Harbor task → grade an agent's replica.
2. **21 final tasks** — [`website-rl-eval-harbor/`](website-rl-eval-harbor/), inventory +
   distribution in [`docs/tasks.md`](docs/tasks.md). 6 easy / 7 medium / 8 hard, 11 site types,
   7 aesthetics.
3. **The visual evaluation report** — [`docs/evaluation.md`](docs/evaluation.md): running Opus 4.7
   on every task, how the grader scores it, why higher grades mean better replicas, and the
   patterns the model struggles with. Figures in [`docs/figures/`](docs/figures/), raw numbers in
   [`results/`](results/).

## How I thought through it (the reasoning trail)

The trial is judged on research taste, so the *why* behind every decision is written down
([`docs/overview.md`](docs/overview.md) is the architecture map):

- [`decisions.md`](decisions.md) — **D1–D12**, every design decision with its rationale and the
  evidence that drove it (e.g. why perceptual/CLIP/VLM graders were dropped, why the reward is a
  geometric mean, why the reference must render in the agent's own font image).
- [`findings.md`](findings.md) — **F1–F11**, empirical results from real runs and the degradation
  ladders (the grader's monotonicity proof, the binding-constraint analysis, the font-environment
  bug and its fix).
- [`metrics.md`](metrics.md) — the grader internals, dimension by dimension.
- [`ideas.md`](ideas.md) — open ideas and the road not (yet) taken.
- [`task.md`](task.md) — the original brief.

## Pipeline shape

```
[Generator]  two-stage LLM writes a real multi-page site (HTML/CSS source)   pipeline/generate.py
                  ↓  render IN the task's Docker image (shared font world)    pipeline/render.py
             reference screenshots + boxes  ── the grading ground truth
                  ↓
[Agent]      Claude Code (Opus 4.7) sees ONLY the screenshots → writes its HTML/CSS
                  ↓  render the SAME way, same image
[Grader]     5 deterministic offline dims → weighted geometric mean → continuous reward
                                                                              pipeline/grader.py
```

The render step is one shared module used for the reference *and* the agent, in the *same* Docker
image — so fonts/engine match and a perfect copy can actually score 1.0 (this was a real bug we
found and fixed; see [`findings.md`](findings.md) F10/F11).

## Repo map

```
pipeline/            the recipe: generate.py · render.py · grader.py · metrics/ · templates/
build_task.sh        packager: generate → build env image → render reference in-image → assemble task
website-rl-eval-harbor/   the 21 generated Harbor tasks (raw job outputs git-ignored)
make_*_ladder.py     degradation-ladder generators (content / colour / typography) — the grader trust gate
ladder_grade.py, grade.py    grading helpers
scripts/             extract_results.py · make_figures.py · make_examples.py · make_task_inventory.py
results/             distilled eval results (per_trial.csv · per_task.csv · summary.json)
docs/                evaluation.md (visual report) · tasks.md (inventory) · figures/
*.md (root)          the reasoning trail (context / decisions / findings / metrics / ideas / task)
```

## Setup

```bash
python3.13 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # local rendering / ladders
# secrets — never committed:
cp .env.example .env                 # then add your key
export ANTHROPIC_API_KEY=sk-ant-...  # generation + the agent
# Modal (to run tasks on Modal instead of local Docker):
modal token set --token-id ... --token-secret ...
```
Generation and the agent need `ANTHROPIC_API_KEY`; **the grader is fully offline** (no key, no
network — `numpy`/`scipy`/`pillow` + the `tesseract` binary only).

## Quickstart

```bash
# 1. generate + package a task (needs ANTHROPIC_API_KEY + local Docker)
./build_task.sh kiwi hard

# 2. run Claude Code (Opus 4.7) on it and score it
cd website-rl-eval-harbor/eval-kiwi-hard && ../../venv/bin/harbor run -c run.agent.yaml

# 3. validate the grader's monotonicity (the trust gate)
venv/bin/python make_type_ladder.py --mode family && venv/bin/python ladder_grade.py --name eval-apple-easy-family

# 4. regenerate the report data + figures from the runs
venv/bin/python scripts/extract_results.py && venv/bin/python scripts/make_figures.py
```

## Headline result

Across the 21-task fleet (Opus 4.7, 3 trials each, 0 errors), **reward tracks difficulty
monotonically — easy 0.776 > medium 0.765 > hard 0.755** — and within-task spread is tight
(≤0.024). Higher grades correspond to visibly closer replicas; the model's consistent weakness is
within-block render fidelity (fonts) and complex illustrations. Full report:
[`docs/evaluation.md`](docs/evaluation.md).

![reward by difficulty](docs/figures/reward_by_difficulty.png)
