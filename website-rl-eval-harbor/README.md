# website-rl-eval-harbor

Self-contained **Harbor tasks** for the website-replication eval, one per seed.
Each is built by `build_task.sh` and is a standalone Harbor task directory.

## Build a task

```bash
source ~/.zshrc                       # ANTHROPIC_API_KEY (generation needs it)
./build_task.sh quartz-99             # → eval-quartz-99/
```

The script generates the reference site, renders its screenshots + element boxes,
and lays out the Harbor task. Run it from anywhere — it resolves the repo root itself.

## Task layout (what Harbor expects)

```
eval-<seed>/
├── task.toml             # manifest (name, timeouts, workdir /app, allow_internet)
├── instruction.md        # the agent's prompt (sees only ./target/*.png, writes ./site/)
├── environment/
│   ├── Dockerfile        # ubuntu + playwright + grader deps; COPY target→/app/target, pipeline→/opt
│   ├── target/*.png      # screenshots, seeded into /app/target — the agent's ONLY input
│   └── pipeline/         # render + grader code, baked into the image (PYTHONPATH=/opt)
├── tests/                # copied to /tests at VERIFY time only (hidden from the agent)
│   ├── test.sh           # render /app/site → grade vs reference → /logs/verifier/reward.txt
│   └── reference/        # reference *.png + *.boxes.json (grading ground truth)
└── solution/
    ├── solve.sh          # cp /solution/site → /app/site  (the oracle ~1.0 anchor)
    └── site/             # the reference HTML/CSS
```

Key in-container paths: agent works in **/app**, sees **/app/target**, writes **/app/site**;
the verifier renders `site/*.html` and compares to `/tests/reference` (color + structure
dimensions only for now — fully offline, no torch/API).

## Run it

Harbor jobs run only via `harbor run -c <config.yaml>` (there are no `-p/-a/-m`
flags). `build_task.sh` writes two ready configs into each task dir. **This whole
directory is the Harbor "dataset"** — a local dataset is just a folder of task
dirs; the configs point `path` here and filter to one task via `task_names`.

```bash
# 1. sanity-check the grader ceiling — the reference solution should score ~1.0
venv/bin/harbor run -c eval-<seed>/run.oracle.yaml

# 2. run the real agent (Claude Code), 10 attempts
venv/bin/harbor run -c eval-<seed>/run.agent.yaml

# browse trajectories + rewards
venv/bin/harbor view website-rl-eval-harbor/jobs
```

To run **all** `eval-*` tasks as one dataset, use a config that omits
`task_names` and points `path` at this directory. The agent name is
`claude-code`; set `model_name` to your exact Opus 4.7 id (defaults to the
`opus` alias).

## Notes / TODO
- **Perceptual + VLM dims are off** in the verifier (color + structure only) so the
  container stays offline and dependency-light. Re-enabling perceptual needs torch +
  the embedding weights in the image; VLM needs `ANTHROPIC_API_KEY` wired into the
  verifier env.
- `eval-<seed>/.build/` keeps the raw generated site + reference renders for inspection.
