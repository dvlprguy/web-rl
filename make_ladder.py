"""Degradation ladder — controllably damage a truth site to test grader monotonicity.

Takes a reference site (dir of *.html + style.css) and emits a series of rungs that
progressively DROP content. The suffix = % of elements RETAINED:

    eval-apple-easy-90  → 10% of elements dropped   (barely damaged)
    eval-apple-easy-50  → 50% dropped
    eval-apple-easy-0   → 100% dropped              (empty body)

Removal is NESTED: each harder rung's removals strictly contain the easier rung's
(we keep peeling random leaf elements off ONE parse, snapshotting at each level), so
the underlying content curve is monotone by construction — any non-monotonicity in
the resulting REWARD is the grader's, not the input's. Seeded per page → reproducible.

    venv/bin/python make_ladder.py
    venv/bin/python make_ladder.py --truth <site_dir> --out <dir> --name <prefix>
"""

import argparse
import shutil
import zlib
from pathlib import Path
from random import Random

from bs4 import BeautifulSoup

ap = argparse.ArgumentParser()
ap.add_argument("--truth", default="website-rl-eval-harbor/eval-apple-easy/solution/site")
ap.add_argument("--out", default="ladder")
ap.add_argument("--name", default="eval-apple-easy")
ap.add_argument("--seed", type=int, default=42)
# Each value = percent of body elements to RETAIN at that rung.
ap.add_argument("--levels", default="90,80,60,50,25,10,5,0")
args = ap.parse_args()

truth = Path(args.truth)
out_base = Path(args.out)
levels = [int(x) for x in args.levels.split(",")]
pages = sorted(truth.glob("*.html"))
css = truth / "style.css"

# rung dir per level (created fresh)
rung_dir = {L: out_base / f"{args.name}-{L}" for L in levels}
for d in rung_dir.values():
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    if css.exists():
        shutil.copy(css, d / "style.css")


def body_elements(soup):
    body = soup.body or soup
    return body.find_all(True)


print(f"truth: {truth}   levels (retain %): {levels}\n")
print(f"{'page':12s}{'N':>5s}  " + "".join(f"{L:>6d}" for L in levels))
print("-" * (19 + 6 * len(levels)))

for f in pages:
    soup = BeautifulSoup(f.read_text(), "html.parser")
    body = soup.body or soup
    N = len(body_elements(soup))
    rng = Random(args.seed ^ zlib.crc32(f.stem.encode()))

    counts = []
    # Descend through levels (already sorted high→low keep), peeling leaves.
    for L in sorted(levels, reverse=True):
        keep = round(L / 100 * N)
        while len(body_elements(soup)) > keep:
            leaves = [e for e in body_elements(soup) if not e.find(True)]
            if not leaves:
                break
            rng.choice(leaves).decompose()
        kept = len(body_elements(soup))
        counts.append((L, kept))
        (rung_dir[L] / f.name).write_text(str(soup))

    by_level = dict(counts)
    print(f"{f.stem:12s}{N:5d}  " + "".join(f"{by_level[L]:6d}" for L in levels))

print(f"\nwrote {len(levels)} rungs × {len(pages)} pages → {out_base}/{args.name}-*")
