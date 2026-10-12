"""v0.5: convert docs/model-profiles.md tables to --capability-scores JSON.

The .md is human-maintained (source of truth). This script parses the
three score columns (股票/15, 代码/15, 量化/20), normalizes each to
0.0-1.0, and blends them into a single capability score per model.

Blend weights: stock 40%, code 40%, quant 20%.
Missing dimension -> that weight redistributes to the others.

Usage:
    python3 -m tt.profiles_to_scores [profiles.md] > capability-scores.json
    python3 thinktank.py ask --capability-scores capability-scores.json ...
"""

import json
import os
import re
import sys

DEFAULT_MD = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "docs", "model-profiles.md")

# column max scores for normalization
COL_MAX = {"stock": 15.0, "code": 15.0, "quant": 20.0}
WEIGHTS = {"stock": 0.4, "code": 0.4, "quant": 0.2}


def parse_profiles(path):
    """Parse markdown tables. Returns {model_id: {dim: score}}."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    out = {}
    # match table rows: | model | ... | stock | code | quant | note |
    # header determines column positions
    current_header = None
    for line in text.split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            current_header = None
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if "模型" in cells[0]:
            # header row: find score column indices
            current_header = {}
            for i, c in enumerate(cells):
                if "股票" in c:
                    current_header["stock"] = i
                elif "代码" in c:
                    current_header["code"] = i
                elif "量化" in c:
                    current_header["quant"] = i
            continue
        if current_header is None or set(cells) == {"---"}:
            continue
        if len(cells) < 2 or cells[0].startswith("---"):
            continue
        model = cells[0]
        if not model or model == "模型":
            continue
        scores = {}
        for dim, idx in current_header.items():
            if idx < len(cells):
                v = cells[idx].strip().strip("*")
                try:
                    scores[dim] = float(v)
                except ValueError:
                    pass  # "—" or empty = untested
        if scores:
            out[model] = scores
    return out


def blend(scores):
    """Weighted blend of normalized dimension scores -> 0.0-1.0."""
    total_w, total = 0.0, 0.0
    for dim, raw in scores.items():
        mx = COL_MAX.get(dim)
        w = WEIGHTS.get(dim, 0)
        if mx and w:
            total += (min(raw, mx) / mx) * w
            total_w += w
    if total_w == 0:
        return 0.5  # no scores at all -> neutral
    return round(total / total_w, 3)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MD
    profiles = parse_profiles(path)
    out = {m: blend(s) for m, s in profiles.items()}
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
