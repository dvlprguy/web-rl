# Trajectory Analysis — Fruit Eval Environments

Deep per-environment analysis of every fruit-named Harbor eval (21 envs), built by fanning out one subagent per env to read **everything** in each job folder: `result.json`, `config.json`, `trial.log`/`job.log`, the multi-MB `agent/trajectory.json` + `agent/claude-code.txt`, `verifier/grade_report.json` + `test-stdout.txt` + `reward.txt`, and the `artifacts/app/{target,site}` outputs. Agent under test: **Claude Code / Opus 4.7**. Grader: offline weighted **geometric mean** over 5 dimensions (`structure` w=1.0, `block_color` 0.6, `text_color` 0.3, `block_ssim` 0.3, `edge_ssim` 0.3), floor `1e-3`, averaged across pages (missing page → 0).

---

## Cross-environment synthesis

### Reward leaderboard (mean of graded trials)

| Env | Difficulty | Mean reward | Trials | Note |
|---|---|---|---|---|
| pear-easy | easy | **0.809** | 3 | highest; flat web-safe-font design + one self-rendering trial |
| apple-easy | easy | 0.796 | 3 | |
| peach-medium | medium | 0.796 | 3 | reward flat across 10× cost spread |
| lemon-easy | easy | 0.784 | 3 | |
| raspberry-hard | hard | 0.778 | 3 | well-calibrated "hard", all blind |
| fig-hard | hard | 0.775 | 3 | render-loop worth ~0.05 here |
| papaya-medium | medium | 0.775 | 3 | font-family mis-inference |
| lime-medium | medium | 0.774 | 3 | |
| guava-easy | easy | 0.773 | 3 | |
| banana-medium | medium | 0.766 | 3 | |
| pomegranate-hard | hard | 0.765 | 3 | σ≈0.004; render-loop bought ~0 |
| pineapple-hard | hard | 0.762 | 3 | background-tint global miss |
| grape-easy | easy | 0.761 | 3 | |
| plum-medium | medium | 0.760 | 3 | stripe-vs-gradient imagery miss |
| melon-hard | hard | 0.757 | 3 | one trial hit `/tmp` ENOSPC |
| cherry-hard | hard | 0.750 | 3 | σ≈0.0006, extreme stability |
| coconut-medium | medium | 0.744 | 3 | |
| blueberry-hard | hard | 0.741 | 3 | render-blind sandbox |
| mango-medium | medium | 0.740 | 3 | iteration depth mattered |
| apricot-easy | easy | 0.733 | 3 | lowest easy; neon glow font |
| kiwi-hard | hard | 0.712 | 2 (+1 errored) | **verifier infra crash**, not agent |

### Seven findings that hold across (nearly) every env

1. **`block_ssim` is the universal binding constraint and the reward ceiling.** In all 21 envs it is the lowest dimension on essentially every page (typically 0.25–0.55 while `block_color` sits 0.91–0.97, `structure` 0.74–0.89). Because the combine is a geometric mean, this single 0.3-weight channel mathematically pins almost every good replica into the ~0.74–0.80 band regardless of how good layout/color are. It measures within-block render fidelity (exact font family/weight, glyph anti-aliasing, fills) — structurally hard to match offline with web-safe fonts against a target's bespoke/display typeface. Several envs' graders literally comment that these weights are "PROVISIONAL — re-run the D9/D10 ladder before locking."

2. **Color is solved; fidelity is the frontier.** `block_color` (~0.95) and `text_color` (~0.89) are near-saturated for any competent Opus run — they contribute almost no discriminative signal. Nearly all ranking signal lives in `structure`, `block_ssim`, and `edge_ssim`.

3. **The dominant behavioral lever is the render-and-compare loop — and it's gated by luck of environment discovery.** The envs split agents into (a) self-verifiers who discovered Playwright/Chromium in the sandbox, rendered their own pages, built side-by-side diffs, and iterated; vs (b) blind one-shotters who probed only for browser *binaries* (`which chromium google-chrome`), missed the Playwright *package*, and submitted without ever seeing their output. Which path a trial took was essentially random per rollout and was the biggest single driver of intra-env variance.

4. **…but the render loop's payoff is wildly inconsistent, and often ~0.** It was worth ~+0.05 in fig-hard and ~+0.03 in guava/pear, but **~0.00 (sometimes negative)** in peach, papaya, lime, pomegranate, pineapple. Reason: the loop fixes layout/height/spacing (which `structure`/`edge_ssim` reward modestly), but the binding constraint is `block_ssim` (fonts/glyphs), which iteration cannot move. This is the single most important grader concern: **reward is frequently NOT monotonic with visible agent effort/fidelity**, which is a weak/contradictory training signal exactly where it matters.

5. **Rewards are extremely stable but compressed.** Intra-env spread is typically 0.01–0.03 (cherry-hard: 0.0006; pomegranate: σ≈0.004). Great for low-noise RL, but the usable dynamic range for *competent* attempts is narrow — good and slightly-worse outputs land within ~0.02–0.05.

6. **Difficulty tier ≠ reward.** Some "hard" envs (fig 0.775, raspberry 0.778) outscore "easy" ones (apricot 0.733, grape 0.761). Reward is driven more by how web-safe-font-friendly the target typography/imagery is (i.e. how reachable `block_ssim` is) than by structural complexity. The "easy/medium/hard" label tracks layout density, but the grader is gated by font fidelity.

7. **Two infra faults, not agent faults, corrupted job-level numbers.** (a) **kiwi-hard** trial `3yGpA3m` produced a complete, gradeable site but the verifier hung in Modal's `process.stdout.read.aio()` for the full 1200 s → `VerifierTimeoutError`, no reward written; the job's reported 0.475 mean is misleading (real ≈0.71). (b) **melon-hard** trial `L6A9hFG` hit `/tmp` ENOSPC during browser probing, was forced to build blind, and scored lowest — environment luck, not reasoning. Both argue for hardening the sandbox (guaranteed renderer, `CLAUDE_CODE_TMPDIR` default, timeout-guarded stdout reads, retry on `VerifierTimeoutError`).

### Recommended actions (grader/env)

- **Re-calibrate or down-weight `block_ssim`** (or make it font-/sub-pixel-tolerant, e.g. mask glyphs and score fill/shape) so reward becomes monotonic with the layout/height fidelity that agents *can* control. Validate every env against its `solution`/oracle to pin the true ceiling — most envs have **no oracle run stored**, so we don't empirically know the top of the range.
- **Make a renderer deterministic and discoverable** (pre-install Chromium on PATH or advertise Playwright in `instruction.md`) so reward measures design skill, not probe-string luck. Today self-verification is a hidden, random difficulty knob.
- **Normalize for page height** before edge/region SSIM (several envs penalize otherwise-faithful pages for trailing whitespace / height mismatch — pineapple, lime, raspberry, peach).
- **Reward semantic HTML in `structure`** is working but agents leak points using `<div>` where the reference used `<section>`/`<header>` (banana). Surfacing this would help.
- **Fix the two infra faults** (kiwi verifier hang, melon ENOSPC) and re-run those jobs.

---

## Per-environment reports

> Each section below is the full deep-dive for one env (per-trial tables, agent behavior, struggles, grader observations, takeaways).

