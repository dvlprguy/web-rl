"""Dimension 4 — constrained VLM rubric judge.

Captures what the deterministic metrics miss (typographic feel, design intent).
To keep it from re-injecting noise we NEVER ask for a raw 0–100: the VLM scores
concrete sub-dimensions against a rubric on a small ordinal 0–4 scale, anchored by
the reference, and we average them. Ordinal rubric scoring is far more stable than
a fine continuous number, and the reference is a perfect anchor.

Kept lighter-weight than the deterministic backbone (see grader_v0.md). May be
dropped from v0 entirely if the ladder shows it adds variance without signal.

Uses litellm vision; model + key from env (VLM_MODEL, ANTHROPIC_API_KEY).
"""

from __future__ import annotations

import base64
import json
import os
import re

VLM_MODEL = os.environ.get("VLM_MODEL", "anthropic/claude-opus-4-7")

_DIMENSIONS = ("layout", "typography", "spacing", "content")

_SYSTEM = """You are a meticulous UI design reviewer. You are shown a REFERENCE \
website screenshot and a CANDIDATE replication of it. Judge ONLY how faithfully the \
candidate reproduces the reference's visual design (ignore functionality).

Score each dimension on an integer 0-4 scale, anchored to the reference:
  0 = unrecognisable / absent   1 = major mismatch   2 = many mismatches   3 = close   4 = near-identical/identical

Dimensions: layout, typography, spacing, content (are the same components present).

Output STRICT JSON only, no prose, no fences:
{"layout": int, "typography": int, "spacing": int, "content": int}"""


def _data_url(path) -> str:
    b = base64.b64encode(open(path, "rb").read()).decode()
    return f"data:image/png;base64,{b}"


def _strip_json(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n", "", t)
        t = re.sub(r"\n```$", "", t.strip())
    return t.strip()


def vlm_rubric(ref_png, cand_png) -> dict[str, float]:
    """Raw integer 0–4 rubric sub-scores, one per dimension (layout, color,
    typography, spacing, content). The single VLM dimension is their mean."""
    import litellm

    litellm.suppress_debug_info = True
    resp = litellm.completion(
        model=VLM_MODEL,
        max_tokens=200,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "REFERENCE:"},
                    {"type": "image_url", "image_url": {"url": _data_url(ref_png)}},
                    {"type": "text", "text": "CANDIDATE:"},
                    {"type": "image_url", "image_url": {"url": _data_url(cand_png)}},
                    {"type": "text", "text": "Score the candidate. JSON only."},
                ],
            },
        ],
    )
    raw = resp.choices[0].message.content
    scores = json.loads(_strip_json(raw))
    sub = {d: float(scores[d]) for d in _DIMENSIONS if d in scores}
    if not sub:
        raise ValueError(f"VLM returned no usable scores: {raw[:200]}")
    return sub


def vlm_score(ref_png, cand_png) -> float:
    """Average of the rubric sub-scores, normalised to [0, 1]."""
    sub = vlm_rubric(ref_png, cand_png)
    return sum(sub.values()) / (len(sub) * 4.0)  # mean of 0–4 → [0, 1]
