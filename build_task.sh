#!/usr/bin/env bash
#
# build_task.sh — assemble ONE Harbor task for the website-replication eval.
#
#   ./build_task.sh <seed> [easy|medium|hard]      # difficulty default: medium
#
# Produces website-rl-eval-harbor/eval-<seed>/ laid out exactly how Harbor expects
# a task directory (task.toml / instruction.md / environment / tests / solution).
# Everything for this seed lives under that one folder — including a .build/ with the
# raw generated site + reference renders, kept for transparency.
#
# Pipeline per seed:
#   1. generate the reference site      (pipeline.generate — needs ANTHROPIC_API_KEY)
#   2. render reference screenshots+boxes (pipeline.render, extract_boxes=True)
#   3. lay out the Harbor task:
#        - screenshots  → environment/target/  (COPY'd to /app/target: agent input)
#        - ref + boxes  → tests/reference/      (verify-time only: grading ground truth)
#        - grader code  → environment/pipeline/ (baked into the image)
#        - the site     → solution/site/        (the ~1.0 oracle anchor)
#
# How the pieces map in-container (see decisions D5):
#   /app/target/<stem>.png   the agent's only input (screenshots)
#   /app/site/<stem>.html    where the agent writes its replica
#   /tests/reference/...      reference png+boxes, hidden from the agent
#   /logs/verifier/reward.txt the single-float reward the verifier writes
set -euo pipefail

# --- resolve paths --------------------------------------------------------- #
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # repo root (has pipeline/, venv/)
DATASET="$ROOT/website-rl-eval-harbor"                  # the Harbor dataset dir (task dirs land here)
PY="$ROOT/venv/bin/python"
mkdir -p "$DATASET"

seed="${1:-}"
difficulty="${2:-medium}"
if [[ -z "$seed" ]]; then
  echo "usage: $0 <seed> [easy|medium|hard]   (difficulty default: medium)" >&2
  exit 2
fi
case "$difficulty" in
  easy|medium|hard) ;;
  *) echo "bad difficulty '$difficulty' (expected easy|medium|hard)" >&2; exit 2 ;;
esac
if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "ANTHROPIC_API_KEY not set (generation needs it). Run: source ~/.zshrc" >&2
  exit 2
fi

task_id="eval-$seed-$difficulty"   # difficulty in the dir name → one seed can exist at every tier
TASK="$DATASET/$task_id"
BUILD="$TASK/.build"
echo ">> building task for seed '$seed' (difficulty: $difficulty) → $TASK"
rm -rf "$TASK"
mkdir -p "$BUILD" "$TASK/environment/target" "$TASK/tests/reference" "$TASK/solution/site"

# --- 1. generate the reference site --------------------------------------- #
echo ">> [1/4] generating site (two-stage LLM)…"
"$PY" -m pipeline.generate "$BUILD/site" --seed "$seed" --difficulty "$difficulty"

# --- 2. build the env image (so the reference renders INSIDE it) ---------- #
# The reference MUST render in the same image the agent/verifier uses, or fonts/
# engine differ and even a perfect replica is capped below 1.0 (F11). So we lay down
# the grader code + Dockerfile now, build the image, and render the reference in a
# container of it (step 3). Local Docker is required at build time here, independent
# of where the job later runs (modal or docker).
echo ">> [2/4] building env image (fonts) for in-image reference render…"
cp -r "$ROOT/pipeline" "$TASK/environment/pipeline"
find "$TASK/environment/pipeline" -name '__pycache__' -type d -prune -exec rm -rf {} +

# environment/Dockerfile — ubuntu + playwright (renders here) + open font palette
# (F10/F11) + grader code on PYTHONPATH + screenshots seeded into /app/target.
cat > "$TASK/environment/Dockerfile" <<'EOF'
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive

# Python + curl (claude_code installs its own CLI at runtime via the adapter).
# tesseract-ocr is the OCR backend for the LLEM text_color dimension.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip curl ca-certificates tesseract-ocr \
 && rm -rf /var/lib/apt/lists/*

# Verifier deps: render (playwright) + the offline grader dims. numpy/pillow for
# colour + crops, scipy for LLEM block-matching, SSIM and Sobel edge maps (OCR via
# the tesseract binary above). No torch/litellm — perceptual (D6) and VLM (D8) are
# dropped, so grading is fully offline: no API key, no network at verify time.
RUN pip3 install --no-cache-dir --break-system-packages playwright numpy pillow scipy \
 && playwright install --with-deps chromium

# Fonts (F10/F11) — reference AND agent render in THIS image, so they share one font
# world (the reference is rendered in a container of this image at build time; see
# build_task.sh). A broad open palette (apt) + condensed/display/mono faces Google
# ships but apt doesn't, so designs render distinctively offline instead of collapsing
# to Liberation. fc-cache so Chromium sees them.
RUN apt-get update && apt-get install -y --no-install-recommends \
        fontconfig fonts-liberation fonts-dejavu fonts-noto-core fonts-urw-base35 \
        fonts-ebgaramond fonts-cantarell fonts-firacode fonts-open-sans fonts-lato \
        fonts-roboto-unhinted \
 && mkdir -p /usr/share/fonts/truetype/extra && cd /usr/share/fonts/truetype/extra \
 && for u in \
      "ofl/robotocondensed/RobotoCondensed[wght].ttf" \
      "ofl/oswald/Oswald[wght].ttf" \
      "ofl/archivonarrow/ArchivoNarrow[wght].ttf" \
      "ofl/bebasneue/BebasNeue-Regular.ttf" \
      "ofl/jetbrainsmono/JetBrainsMono[wght].ttf" \
      "ofl/spacemono/SpaceMono-Regular.ttf" \
      "ofl/inter/Inter[opsz,wght].ttf" \
      "ofl/playfairdisplay/PlayfairDisplay[wght].ttf" \
      "ofl/sourceserif4/SourceSerif4[opsz,wght].ttf" \
    ; do curl -gfsSL -o "$(basename "$u")" "https://github.com/google/fonts/raw/main/$u" || true; done \
 && rm -rf /var/lib/apt/lists/*

# Resolve common proprietary family names (from generated CSS) → installed open faces,
# so designs render distinctively. NOTE: this aliases, it does not constrain the
# generator (kept free to pick any font; same-image rendering makes even an
# un-installed font fair — both sides fall back identically).
RUN printf '%s\n' \
 '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>' \
 '<alias><family>SF Mono</family><prefer><family>JetBrains Mono</family></prefer></alias>' \
 '<alias><family>Consolas</family><prefer><family>JetBrains Mono</family></prefer></alias>' \
 '<alias><family>Arial Narrow</family><prefer><family>Archivo Narrow</family></prefer></alias>' \
 '<alias><family>Helvetica Neue Condensed</family><prefer><family>Archivo Narrow</family></prefer></alias>' \
 '<alias><family>Palatino Linotype</family><prefer><family>P052</family></prefer></alias>' \
 '<alias><family>Hoefler Text</family><prefer><family>EB Garamond</family></prefer></alias>' \
 '<alias><family>Iowan Old Style</family><prefer><family>Source Serif 4</family></prefer></alias>' \
 '<alias><family>Big Caslon</family><prefer><family>Playfair Display</family></prefer></alias>' \
 '<alias><family>Segoe UI</family><prefer><family>Open Sans</family></prefer></alias>' \
 '<alias><family>Helvetica Neue</family><prefer><family>Inter</family></prefer></alias>' \
 '</fontconfig>' > /etc/fonts/conf.d/99-eval-aliases.conf \
 && fc-cache -f

# Grader + render code, importable as `pipeline.*`
COPY pipeline /opt/pipeline
ENV PYTHONPATH=/opt

# Agent input: the target screenshots, seeded into the workdir before the agent runs.
COPY target /app/target

WORKDIR /app
EOF

# target/ must exist for the COPY (created empty above); the in-image render below
# fills it. Harbor rebuilds the image with the populated target/ at job time.
IMG="eval-${seed}-${difficulty}-env:build"
docker build -t "$IMG" "$TASK/environment"

# --- 3. render reference screenshots + boxes IN-IMAGE --------------------- #
echo ">> [3/4] rendering reference in-image (same font world as the agent)…"
mkdir -p "$BUILD/ref"
docker run --rm -v "$BUILD/site":/in:ro -v "$BUILD/ref":/out "$IMG" \
  python3 -c "from pipeline.render import capture_site; capture_site('/in','/out',extract_boxes=True)"

# page stems (the I2 filename contract) come straight from the rendered pages
stems=()
for f in "$BUILD"/ref/*.png; do stems+=("$(basename "$f" .png)"); done
echo ">> pages: ${stems[*]}"

# --- 4. lay out the rest of the Harbor task ------------------------------- #
echo ">> [4/4] assembling Harbor task dir…"

# screenshots → agent input (environment/target, COPY'd to /app/target); also refresh
# the just-built image's empty target so a local docker run has the screenshots too.
cp "$BUILD"/ref/*.png "$TASK/environment/target/"
# reference png + boxes → grading ground truth (tests/, hidden from agent)
cp "$BUILD"/ref/*.png "$BUILD"/ref/*.boxes.json "$TASK/tests/reference/"
# the site HTML/CSS → the oracle solution (~1.0 anchor); drop metadata json
cp "$BUILD"/site/*.html "$BUILD"/site/*.css "$TASK/solution/site/" 2>/dev/null || true

# instruction.md — fill the template's {page_list}/{html_list} from the stems
"$PY" - "$ROOT/pipeline/templates/instruction.md" "$TASK/instruction.md" "${stems[@]}" <<'PY'
import sys
template, out, *stems = sys.argv[1:]
page_list = "\n".join(f"- `target/{s}.png`" for s in stems)
html_list = ", ".join(f"site/{s}.html" for s in stems) + ", site/style.css"
text = open(template).read().replace("{page_list}", page_list).replace("{html_list}", html_list)
open(out, "w").write(text)
PY

# task.toml
cat > "$TASK/task.toml" <<EOF
version = "1.0"

[task]
name = "website-rl-eval/$task_id"
description = "Replicate a generated multi-page website design from its screenshots (static HTML/CSS)."

[metadata]
seed = "$seed"
difficulty = "$difficulty"

[verifier]
timeout_sec = 1200.0

[agent]
timeout_sec = 7200.0

[environment]
build_timeout_sec = 1800.0
allow_internet = true
workdir = "/app"
EOF

# (environment/Dockerfile was written + the image built in step 2 above, so the
#  reference could render inside it. Nothing to do here.)

# tests/test.sh — the verifier. Renders the agent's site through the SAME render
# path, grades it against the bundled reference (color+structure only → fully
# offline, no API/torch), writes the reward.
cat > "$TASK/tests/test.sh" <<'EOF'
#!/usr/bin/env bash
set -uo pipefail
mkdir -p /logs/verifier

# No site produced → reward 0 (don't crash the verifier).
if ! ls /app/site/*.html >/dev/null 2>&1; then
  echo "no /app/site/*.html produced → reward 0"
  echo "0.0" > /logs/verifier/reward.txt
  exit 0
fi

# 1. render the agent's site (with boxes) via the single render path
python3 - <<'PYEOF'
from pipeline.render import capture_site
capture_site("/app/site", "/tmp/cand", extract_boxes=True)
PYEOF

# 2. grade candidate vs. bundled reference — DEFAULT_WEIGHTS (structure + colour +
#    region SSIM/edge dims), all offline (no API/network; VLM/perceptual dropped).
python3 - <<'PYEOF'
from pipeline.grader import grade_site, GraderConfig, write_reward
cfg = GraderConfig()  # DEFAULT_WEIGHTS — single source of truth with grade.py
res = grade_site("/tests/reference", "/tmp/cand", cfg=cfg)
for stem, p in sorted(res.pages.items()):
    print(f"  {stem:12s} {p['combined']:.3f}  {p.get('dimensions', {})}")
print(f"REWARD = {res.reward:.4f}")
write_reward(res, "/logs/verifier")
PYEOF
EOF
chmod +x "$TASK/tests/test.sh"

# solution/solve.sh — the oracle: drop the reference site into /app/site (~1.0).
cat > "$TASK/solution/solve.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir -p /app/site
cp -r /solution/site/. /app/site/
EOF
chmod +x "$TASK/solution/solve.sh"

# --- run configs ----------------------------------------------------------- #
# Harbor jobs run ONLY via `harbor run -c <config.yaml>` (no -p/-a/-m flags). A
# local "dataset" is just a folder of task dirs: point `path` at this directory
# and filter to this one task with `task_names`. The agent name is `claude-code`.
#
# The execution backend is `environment.type`; Harbor DEFAULTS this to `docker`
# (local Docker daemon). To run on Modal we must set it explicitly — Modal builds
# the image from environment/Dockerfile via Image.from_dockerfile(context=environment/).
# Override with: HARBOR_ENV_TYPE=docker ./build_task.sh <seed>  (cheap local smoke test).
#
# Host prereqs for Modal: `modal token set` (from the invite link) once, and
# ANTHROPIC_API_KEY in the host shell — the claude-code adapter forwards it in.
ENV_TYPE="${HARBOR_ENV_TYPE:-modal}"

cat > "$TASK/run.oracle.yaml" <<EOF
# Validate the grader ceiling: the reference solution should score ~1.0.
job_name: "$task_id-oracle"
jobs_dir: "$DATASET/jobs"
n_attempts: 1
environment:
  type: "$ENV_TYPE"
agents:
  - name: "oracle"
datasets:
  - path: "$DATASET"
    task_names: ["$task_id"]
EOF

cat > "$TASK/run.agent.yaml" <<EOF
# Run the real agent (Claude Code, Opus 4.7) on this task. Paths are relative to
# this config file's dir (the task dir), so jobs land in <task>/jobs.
jobs_dir: ./jobs
n_attempts: 3

orchestrator:
  n_concurrent_trials: 3

environment:
  type: $ENV_TYPE
  kwargs:
    sandbox_timeout_secs: 14400        # 4h hard ceiling
    sandbox_idle_timeout_secs: 3600    # 1h of inactivity before culling

agents:
  - name: claude-code
    model_name: anthropic/claude-opus-4-7
    kwargs:
      disallowed_tools: "WebSearch WebFetch"

tasks:
  - path: .


artifacts:
  - /app/
EOF

echo ">> done: $TASK"
echo ">> validate grader ceiling (oracle ≈ 1.0):"
echo "     $ROOT/venv/bin/harbor run -c $TASK/run.oracle.yaml"
echo ">> run the agent 10x:"
echo "     $ROOT/venv/bin/harbor run -c $TASK/run.agent.yaml"
echo ">> browse results:   $ROOT/venv/bin/harbor view $DATASET/jobs"
