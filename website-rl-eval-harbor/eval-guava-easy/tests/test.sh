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
