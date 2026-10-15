"""Seed skill: stock-analysis.

Wraps tt/stock_context.py as a skill. Reads ticker/position/plan from the
shared context, runs the data provider, puts structured output back.
"""

import subprocess
import json


def run(ctx):
    ticker = ctx.get("ticker")
    if not ticker:
        raise ValueError("stock-analysis: ctx missing 'ticker'")
    position = ctx.get("position", "")
    plan = ctx.get("plan", "")

    r = subprocess.run(
        ["python3", "-m", "tt.stock_context", ticker],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError("stock_context failed: %s" % r.stderr[:300])
    try:
        data = json.loads(r.stdout)
    except ValueError:
        # stock_context prints human-readable; wrap it explicitly
        # (not a silent fallback — the raw text is preserved for inspection)
        data = {"_raw_text": r.stdout[:4000],
                "_note": "non-JSON output wrapped"}

    out = {
        "ticker": ticker,
        "position": position,
        "plan": plan,
        "indicators": data,
    }
    ctx.put("stock-analysis", out)
    return out
