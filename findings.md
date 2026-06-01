# Findings

Empirical companion to `decisions.md`. **Decisions** record *what we chose and why*;
**findings** record *what the evidence actually showed* — ladder curves, real agent-run
breakdowns, and operational gotchas. Each finding cross-refs the decision it informs.

As of this writing the grader's active dimensions are `structure`, `block_color`,
`block_ssim`, `edge_ssim`, `text_color` (combined as a weighted geometric mean; global
`color` dropped). See `grader.py` `DEFAULT_WEIGHTS`.

---

## F1 — The reward is monotone with true visual fidelity, with an honest ceiling and floor

Proven on controlled degradation ladders (damage a perfect site in nested steps, re-grade;
the input gets strictly worse by construction, so any wobble is the grader's fault). Refs
D9, D12.

- **Content drop** (remove elements): reward 1.0000 → 0.004, strictly monotone. Perfect copy
  = 1.0, empty page ≈ 0. The multiplicative combine makes `structure`'s honest zero drag the
  whole reward to ~0 even when colour still reads ~0.85 — no single dimension can prop up a
  stripped page (the anti-gaming property, confirmed on real data).
- **Typography** (fonts wrong, layout+colour fixed): `block_ssim` 1.0 → 0.26, `edge_ssim`
  1.0 → 0.85; off-axis dims stay ~flat (colours 0.93–0.97, `structure` leaks only to ~0.92
  from real text reflow). Monotone through the meaningful range.
- **Colour, lightness inversion**: `block_color` 1.0 → 0.45, reward 1.0 → 0.42, strictly
  monotone.

**Caveat (real, logged):** at the *saturated tail* of a ladder — once a dimension has already
collapsed — the curve enters a **~0.01–0.02 noise floor** (OCR jitter on maximally-mangled
text) and the zero-tolerance monotonicity check flags sub-0.02 upticks as "non-mono". This is
the grader's reproducibility limit, not a real reversal. It argues for a tolerance-banded
monotonicity check rather than zero-tolerance arrows (open item).

## F2 — `block_ssim` is the binding constraint on real agent output

From the Modal run (Claude Code, Opus 4.7, 3 trials each on the 3 tasks using the current
grader; per-dimension means across trials × pages):

| task | reward | structure | block_color | block_ssim | edge_ssim | text_color |
|---|---|---|---|---|---|---|
| eval-cobalt-9-hard | 0.751 | 0.843 | 0.913 | **0.376** | 0.648 | 0.827 |
| eval-sandstone-6-medium | 0.708 | 0.777 | 0.925 | **0.337** | 0.564 | 0.824 |
| eval-ember-27-easy | 0.671 | 0.711 | 0.900 | **0.260** | 0.701 | 0.826 |

`block_ssim` (within-block render fidelity — exact fonts, weights, fills, glyph rendering) is
the lowest dimension on every task by a wide margin. The agent gets layout and palette broadly
right but the *fine* within-block rendering is consistently where it loses the most. This is
the same dimension the typography ladder (F1) showed has the widest dynamic range — so it is
doing real, load-bearing work in the reward, not sitting idle.

## F3 — Colours are easy for the agent; type/layout fidelity is hard

Same run. `block_color` (0.90–0.93) and `text_color` (0.82–0.83) are uniformly high across all
tasks — Opus 4.7 reliably reproduces the palette. The reward differences between tasks are
driven almost entirely by `structure` and `block_ssim`. Concretely, **why ember (the "easy"
task) scored lowest**: it has both the lowest `structure` (0.711) and the lowest `block_ssim`
(0.260) — its box layout was the least faithfully reproduced and its within-block rendering the
worst. It is *not* an arbitrary penalty; the dims localise the failure.

## F4 — Grader reproducibility across independent attempts is high

Within-task spread across 3 independent Opus 4.7 trials:

| task | rewards | spread |
|---|---|---|
| eval-quartz-99-hard | 0.805, 0.826, 0.827 | 0.022 |
| eval-cobalt-9-hard | 0.740, 0.751, 0.761 | 0.021 |
| eval-sandstone-6-medium | 0.707, 0.708, 0.709 | **0.002** |
| eval-ember-27-easy | 0.643, 0.668, 0.702 | 0.059 |

Three of four tasks cluster within ≤0.022; the widest is 0.06. Zero trials errored (12/12).
For a training signal this is the property that matters: comparably-good replications get
near-identical scores rather than noise. (Consistent with the ~0.01–0.02 noise floor in F1.)

## F5 — The colour signal is weak under hue rotation, strong under lightness/scheme error

Refs D10, D12. A 180° hue rotation (lightness preserved) moves `block_color` only 1.0 → 0.79
and reward 1.0 → 0.92 — the page is dominated by near-white background / near-dark text that a
hue shift barely changes. Lightness inversion moves `block_color` 1.0 → 0.45 and reward to 0.42.

Interpretation: the small hue range is arguably **correct** (a tint-rotated dark site really is
a closer replica than a light-inverted one), not a bug. `block_color` (per-matched-region mean,
the D11 addition) fixed the D10 "colour has no range" problem **for the scheme/lightness errors
that matter most**, which is what global-histogram `color` could not do — hence global `color`
is dropped. The `text/surface` disentanglement (D12) confirmed `block_color` and `text_color`
are non-redundant: recolouring only glyphs barely moves `block_color` (region mean is
background-dominated); recolouring only surfaces moves it hard.

Known coupling (logged, not yet fixed): `text_color`'s glyph-colour *estimator* depends on
background contrast, so a surface recolour perturbs it even when glyph CSS is unchanged; and it
goes undefined when text ≈ background luminance (invisible text). `block_ssim` is
contrast-coupled (SSIM sees luminance), so it is a render-fidelity signal, not pure typography.

## F6 — Tasks can silently run on different grader versions — rewards are then not comparable

In the Modal run, **eval-quartz-99-hard scored 0.82 but is not comparable to the others.** Its
`tests/test.sh` hardcodes the *old* weights `{color: 0.4, structure: 1.0, text_color: 0.6}` —
the dropped global `color` dim and, crucially, **no `block_ssim`** (the harshest dimension,
F2). The other three tasks pass no explicit weights, so they pick up the current
`DEFAULT_WEIGHTS`. Quartz's high score is a grader-version artifact, not a better replication.

**Lesson:** the verifier must be a single source of truth. A task's `test.sh` should defer to
`DEFAULT_WEIGHTS` (or pin a versioned weight set deliberately), never carry a stale copy. Audit
every task's `test.sh` before a comparative run; consider failing CI on a weights literal that
diverges from `grader.py`.

## F7 — Operational gotchas (Harbor / rendering)

Small things that cost time; recorded so they don't again.

- **`harbor run` resolves `tasks: path: .` relative to the current working directory, not the
  config file's dir.** Must be launched from *inside* the task directory; running from the repo
  root fails with `FileNotFoundError: .../task.toml`.
- **`harbor view` (jobs mode) wants a folder that *directly contains* job directories**, i.e.
  the timestamped run dirs. Pointing it at the tree of *task* dirs renders an empty UI (it lists
  names with `n_total_trials: 0`). Fix: symlink each task's latest `jobs/<ts>/` dir into one
  folder and point the viewer there. (It also auto-bumps to the next free port, e.g. 8081, if
  8080 is held — check the log for the actual URL.)
- **Agent output IS persisted** at `<trial>/artifacts/app/site/` (because `run.*.yaml` sets
  `artifacts: [/app/]`). The reference/truth is at `<task>/solution/site/`; the input
  screenshots the agent saw are at `<task>/target/`. Per-trial reward at
  `<trial>/verifier/reward.txt`; per-dimension breakdown at `<trial>/verifier/grade_report.json`;
  job-level rollup at `jobs/<ts>/result.json` → `stats.evals.*.reward_stats`.
- **Model-generated CSS can carry trailing HTML junk.** The reference `style.css` for
  eval-seed-67 ends with `</style></body></html>`; a CSS parser drops any rule that *follows*
  `</style>`, which silently broke a ladder until the override was inserted before the junk.
  Worth a generator-side strip.
- **Docker build cache is large and reclaimable.** A handful of task builds left ~1.9 GB of
  buildx cache with zero images/containers; `docker builder prune -af` frees it (at the cost of
  a slower first rebuild next time). Modal runs avoid local disk/CPU burden entirely.

## F8 — The grader source ships inside the agent's image (`/opt/pipeline`) — reward-hacking exposure

The shared environment Dockerfile does `COPY pipeline /opt/pipeline` (so the verifier can
`import pipeline.*`), but that image is also where the **agent** works. So during the agent
phase the full grader source — `grader.py` (`DEFAULT_WEIGHTS`, the geometric-mean combine,
floors) and every `metrics/*.py` — is readable at `/opt/pipeline`. A motivated agent (or, worse,
an RL policy being trained against this reward) can read exactly how it is scored and craft
output to game the specific dimensions rather than to genuinely match the design. The reference
design itself is **not** leaked (the Dockerfile copies only `target/` + `pipeline`, never
`solution/`), so this is about the *scoring method*, not the answer key — but for a training
reward that is the more dangerous of the two to expose.

**Mitigation (not yet applied):** keep `pipeline` out of the agent image — inject it only at
verify time (mount/copy into the verifier step), or split into a separate verifier image so the
agent's filesystem never contains the grader. Until then, treat any reward-hacking signal in a
training run as possibly grader-aware, not just design-aware.

## F9 — A "take ~2 hours" time-budget line in the prompt did NOT help (A/B on Modal)

Hypothesis: telling the agent it has a large time budget ("treat this as ~2 hours of focused,
iterative work") would push it to iterate and match more faithfully. We A/B'd it: **run 1** =
original prompt, **run 2** = same prompt + one time-budget line, otherwise identical (Modal,
Claude Code / Opus 4.7, 3 trials/task). Run 2 was cut after 10/12 trials (2 hung — see below);
10 trials is already conclusive.

Per-task mean reward and within-task spread (run 2 ember/sandstone are 2 trials):

| task | run-1 mean (spread) | run-2 mean (spread) | mean Δ | variance |
|---|---|---|---|---|
| eval-cobalt-9-hard | 0.751 (0.021) | 0.753 (0.012) | +0.002 | flat |
| eval-sandstone-6-medium | 0.708 (0.002) | 0.716 (0.004) | +0.008 | flat |
| eval-quartz-99-hard* | 0.819 (0.022) | 0.820 (0.057) | +0.001 | **↑ ~2.5×** |
| eval-ember-27-easy | 0.671 (0.059) | 0.532 / 0.738 | ~0 | **↑ ~3.5×** |

Raw trials — run 1: cobalt [0.740, 0.751, 0.761], sandstone [0.707, 0.708, 0.709], quartz
[0.805, 0.826, 0.827], ember [0.643, 0.668, 0.702]. Run 2: cobalt [0.748, 0.750, 0.760],
sandstone [0.714, 0.718], quartz [0.782, 0.838, 0.839], ember [0.532, 0.738].
*quartz is on the **old** grader in *both* runs (F6), so it's the cleanest apples-to-apples
comparison — and it's the clearest "no help": 0.820 vs 0.819.

**Result: no mean improvement on any task, and variance *rose* on the two looser designs**
(ember, quartz) while the tight tasks (cobalt, sandstone) were unchanged. For a training reward,
*same mean + higher variance = strictly worse* — it adds noise without adding signal.

**It also cost a lot.** Run-2 agents ran ~45–95+ min (vs run 1's quick passes), and **2 trials
hung at the 2-hour agent-timeout wall** — launched the agent, then 77 min of zero activity while
their siblings finished, never wrote a trajectory. The run had to be killed. (Killing the local
orchestrator can also orphan the remote Modal sandboxes until they self-cull on idle/hard
timeout.)

**Interpretation:** an agent doesn't experience wall-clock time; a bare time budget is not an
actionable instruction. Given more "time" with nothing concrete to spend it on, Opus 4.7 tends
to **over-elaborate and drift** from the target rather than tighten the match — hence flat means
and wider spread. More time only helps if it is *render → compare → fix* time. **Decision:
reverted the line from all four `instruction.md`.** The high-leverage version — an explicit
build→render→compare→fix loop (Chromium is already in the image) — remains the prompt change
worth testing (open item 6), but a time budget alone is not it.

## F10 — Reference renders use FALLBACK fonts: the ground truth doesn't show the intended typography (why "easy" ember scored lowest)

Investigating why ember (labelled *easy*) scored lowest of the four. Per-page breakdown
localised it to **home (0.584) and about (0.596)**, driven by **`block_ssim`** (0.130 on about,
0.188 on home — catastrophic) with `structure` also weak; `block_color`/`text_color`/`edge_ssim`
were all fine. So ember loses on *within-block render fidelity* (glyphs), not colour or gross
layout.

**Root cause — fonts.** Ember ("NULLWAVE") is a typography-driven design: a giant **condensed
display wordmark** + **monospace UI text** on black. Its truth CSS asks for
`'Arial Narrow','Helvetica Neue Condensed','Roboto Condensed',sans-serif` (head) and
`'SF Mono','Consolas','Liberation Mono',Menlo,monospace` (body). **None of the distinctive
fonts are installed in the headless ubuntu:24.04 render sandbox** (no web fonts allowed). So:
1. The **reference itself renders a fallback** — the condensed head has no condensed fallback
   installed, so it becomes plain normal-width DejaVu/Liberation sans. The graded ground truth is
   NOT the intended design.
2. The agent, working only from that screenshot, can't read the font name and **over-interprets**
   "big bold display" as `Arial Black`, oversized — its wordmark overflows the viewport. Visually
   confirmed by rendering the agent's output (`_runlogs/ember_agent_render/home.png`) beside the
   reference: same letters, wildly different weight/width/size.
3. `block_ssim` — the most font-sensitive dim (widest range on the typography ladder, F1) —
   correctly but harshly punishes the glyph mismatch, tanking home/about.

**This is systemic, not an ember quirk.** Every task's truth CSS requests fonts absent from the
base image (cobalt: Hoefler/Segoe UI; quartz: Iowan/Palatino; sandstone: SF Mono/Segoe UI;
seed-67: Big Caslon/Hoefler). The difference is **graceful vs catastrophic fallback**:
serif/sans designs fall back to a *similar* family (Liberation/DejaVu serif or sans) and score
fine — that is exactly why quartz/cobalt/sandstone were stable. **Condensed / display / exotic
faces have no metric-compatible fallback installed**, degrade severely *and unpredictably*, and
are where reward gets noisy.

**Implications:**
- **"Difficulty" labels don't predict reward** — they describe target *layout* complexity, not
  *replication* difficulty. Reward actually tracks *how font-dependent + how-degradably the design
  renders*. A minimalist type-forward page (the "easy" ember) is the hard case.
- For a broad, fair distribution this is a confound: a chunk of the reward signal is "how badly do
  the design's fonts fall back in this sandbox," which is unrelated to the agent's design skill.
- It's still a *fair* per-trial penalty (ember's agent could have matched the fallback with a
  restrained normal-weight sans instead of `Arial Black`), and it exposes a real agent failure
  mode: **over-styling display type**. But the underlying ground-truth corruption must be fixed.

**The fix (scalable, two parts — both required):** see open item 7. (a) Install a curated set of
**open-licensed** fonts in `environment/Dockerfile` covering the typographic range (sans, serif,
mono, **condensed**, display) and `fc-cache -f`; (b) constrain the *generator* to draw font
stacks only from that installed palette, so every reference renders as intended and is
reproducible. Neat shortcut for the 5 existing tasks: the generator already lists open fallbacks
in the stacks (e.g. ember's `'Roboto Condensed'`), so simply **installing the open fonts already
named in the fallback chains** (Roboto Condensed, Liberation Mono [present], EB Garamond, etc.)
makes those stacks resolve to a real distinctive face — no regeneration needed. Then re-render
each task's `target/` + `tests/reference/` in the updated image so the ground truth reflects real
type.

## F11 — Proof: reference was rendered in a DIFFERENT environment than the agent; same-image rendering restores the ceiling

Confirmed the F10 root cause is architectural, and quantified it. `build_task.sh` step 2 renders
the reference on the **build host** (`$PY` = the Mac venv → macOS fonts: SF Mono, Arial Narrow,
Hoefler, Palatino all present). The agent + verifier render in **`ubuntu:24.04`** via the *same
code* but a *different environment* (those fonts absent). The render *path* was shared (D3); the
*environment* was not — and fonts live in the environment.

**The smoking-gun number:** render the *identical* ember solution HTML on Mac vs. inside the
ubuntu image and grade one against the other — it scores **0.8908, not 1.0**. `structure` ≈ 1.000
on every page (same HTML → same layout), but `block_ssim` collapses on text-dense pages (about
0.276, services 0.281) purely from font differences. So under the old setup **a perfect replica
was capped at ~0.89** on ember — the agent lost ~11% to an unreachable target, before any skill.

**Fix (F10 steps 1+2), validated on ember:**
- **Step 1 — render the reference inside the same image the agent/verifier uses.** Both sides now
  share one font world, so a perfect copy scores ~1.0 again (same files, same env), and references
  become host-independent / reproducible.
- **Step 2 — install an open font palette in that image** (apt: liberation, dejavu, noto, urw-base35
  [Palatino/Helvetica/Times clones], ebgaramond, firacode, open-sans, lato, roboto[-condensed];
  Google downloads: Archivo Narrow, Oswald, Bebas Neue, JetBrains Mono, Space Mono, Inter, Playfair,
  Source Serif) + fontconfig aliases mapping proprietary names (SF Mono→JetBrains Mono, Arial
  Narrow→Archivo Narrow, Palatino Linotype→P052, Hoefler→EB Garamond, …) → existing designs render
  distinctively without regeneration. ember's reference re-rendered in-image; `target/` +
  `tests/reference/` replaced.

**Note on existing runs:** the run-1/run-2 agent scores are now stale — they were graded against
the Mac reference *and* the agent rendered in a font-bare ubuntu (no palette). A clean eval needs a
fresh agent run in the fonts image (so reference AND agent share it). Re-grading old agent output
against the new reference is still apples-to-oranges (old agent render lacked the palette).

**Status: DONE across the board.** (a) `build_task.sh` restructured — env image now builds in
step 2, reference renders in a container of it in step 3 (was host `$PY`); future tasks are
in-image by construction. (b) Font block + aliases added to the `build_task.sh` Dockerfile template
and all 4 task Dockerfiles. (c) All 4 existing tasks re-rendered in-image — `target/` +
`tests/reference/` replaced (ember/cobalt/quartz/sandstone). Per user: generator font choice is NOT
constrained (kept design diversity); same-image rendering makes even an un-installed font fair (both
sides fall back identically). Remaining: a fresh agent run in the fonts image to get a clean,
reachable-target eval (old run-1/run-2 scores are stale per the note above).

---

### Open items surfaced by these findings
1. Tolerance-banded monotonicity check (kill the false "non-mono" flags at the noise floor; F1).
2. Audit/normalise every task's `test.sh` to one grader version; re-grade quartz on the current
   grader for a comparable number (F6).
3. `text_color` estimator coupling + invisible-text edge case (F5).
4. Generalise the ladders across 2–3 more sites (only eval-seed-67 so far).
5. Move `pipeline` out of the agent image (verify-time only) to close the grader-source
   exposure (F8).
6. Prompt has no self-check loop — the agent never renders/compares its own output, which is
   the likely root of the weak `block_ssim`/`structure` (F2/F3). A build→render→compare→fix
   instruction (Chromium is already in the image) is the high-leverage prompt change; deferred
   for now in favour of a minimal time-budget line (which failed — F9).
7. ~~Install a curated open-font palette + render reference in the same image (F10/F11).~~ **DONE**
   — font palette + aliases in all task Dockerfiles and the `build_task.sh` template; `build_task.sh`
   now renders the reference in-image; all 4 tasks re-rendered. (Generator font choice deliberately
   left unconstrained.) Follow-up: fresh agent run in the fonts image for a clean eval.
