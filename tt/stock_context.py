"""tt/stock_context.py — Build --context-data JSON for stock questions.

Fetches price history from Yahoo Finance, computes technical indicators
(RSI, MACD, moving averages, volume), and outputs context-data JSON
in the schema tt/context.py expects: {"preamble", "facts", "as_of"}.

Usage:
    python3 -m tt.stock_context XOM --position "50 shares long-term account" \\
        --plan "Trim on strength" > /tmp/xom-context.json
    python3 thinktank.py ask --context-data /tmp/xom-context.json ...

Stone 2026-10-14: manual context assembly was too thin (5-day closes only).
Amie's analysis showed what's missing: RSI, MACD, volume, analyst data.
This script automates the technical half; fundamentals still need manual lookup.
"""

import argparse
import datetime
import json
import sys
import urllib.request


def fetch_daily(ticker, days=300):
    """Fetch daily OHLCV from Yahoo Finance chart API."""
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
           "?interval=1d&range=%dd" % (ticker, days))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception as e:
        return None, "fetch failed: %s" % e
    try:
        r = d["chart"]["result"][0]
        ts = r["timestamp"]
        q = r["indicators"]["quote"][0]
        adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose")
        rows = []
        for i, t in enumerate(ts):
            c = q["close"][i]
            if c is None:
                continue
            rows.append({
                "date": datetime.datetime.fromtimestamp(
                    t, tz=datetime.timezone.utc).strftime("%Y-%m-%d"),
                "open": q["open"][i],
                "high": q["high"][i],
                "low": q["low"][i],
                "close": adj[i] if adj and adj[i] else c,
                "volume": q["volume"][i] or 0,
            })
        return rows, None
    except (KeyError, IndexError, TypeError) as e:
        return None, "parse failed: %s" % e


def rsi(closes, period=14):
    """Wilder's RSI."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        chg = closes[i] - closes[i - 1]
        gains.append(max(chg, 0))
        losses.append(max(-chg, 0))
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    return round(100 - 100 / (1 + ag / al), 1)


def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def macd(closes):
    """MACD(12,26,9): returns (macd_line, signal_line, histogram)."""
    if len(closes) < 35:
        return None, None, None
    e12, e26 = ema(closes, 12), ema(closes, 26)
    if e12 is None or e26 is None:
        return None, None, None
    # Build MACD line series for signal
    line_series = []
    for i in range(26, len(closes)):
        e12_i = ema(closes[:i + 1], 12)
        e26_i = ema(closes[:i + 1], 26)
        line_series.append(e12_i - e26_i)
    if len(line_series) < 9:
        return round(line_series[-1], 3), None, None
    signal = ema(line_series, 9)
    line = line_series[-1]
    return round(line, 3), round(signal, 3), round(line - signal, 3)


def sma(values, period):
    if len(values) < period:
        return None
    return round(sum(values[-period:]) / period, 2)


def build(ticker, position="", plan=""):
    rows, err = fetch_daily(ticker)
    if err:
        return {"preamble": "Stock %s technical snapshot (FAILED)" % ticker,
                "facts": {"error": err, "ticker": ticker},
                "as_of": datetime.datetime.now(
                    datetime.timezone.utc).isoformat()}
    closes = [r["close"] for r in rows]
    volumes = [r["volume"] for r in rows]
    last = rows[-1]
    prev = rows[-2] if len(rows) > 1 else last

    rsi14 = rsi(closes)
    m_line, m_sig, m_hist = macd(closes)
    ma10 = sma(closes, 10)
    ma20 = sma(closes, 20)
    ma50 = sma(closes, 50)
    ma200 = sma(closes, 200)
    hi52 = round(max(r["high"] for r in rows[-252:]), 2) if len(rows) >= 60 else None
    lo52 = round(min(r["low"] for r in rows[-252:]), 2) if len(rows) >= 60 else None
    avg_vol_20 = int(sum(volumes[-20:]) / 20) if len(volumes) >= 20 else None

    # 5-day and 10-day momentum
    chg_5d = round((closes[-1] / closes[-6] - 1) * 100, 1) if len(closes) >= 6 else None
    chg_10d = round((closes[-1] / closes[-11] - 1) * 100, 1) if len(closes) >= 11 else None

    facts = {
        "ticker": ticker,
        "current_price": round(last["close"], 2),
        "prev_close": round(prev["close"], 2),
        "day_change_pct": round((last["close"] / prev["close"] - 1) * 100, 2),
        "volume_today": last["volume"],
        "avg_volume_20d": avg_vol_20,
        "rsi_14": rsi14,
        "rsi_signal": ("overbought" if rsi14 and rsi14 >= 70 else
                       "oversold" if rsi14 and rsi14 <= 30 else "neutral"),
        "macd_line": m_line,
        "macd_signal": m_sig,
        "macd_histogram": m_hist,
        "ma_10": ma10,
        "ma_20": ma20,
        "ma_50": ma50,
        "ma_200": ma200,
        "price_vs_ma20_pct": (round((last["close"] / ma20 - 1) * 100, 1)
                              if ma20 else None),
        "price_vs_ma200_pct": (round((last["close"] / ma200 - 1) * 100, 1)
                               if ma200 else None),
        "high_52w": hi52,
        "low_52w": lo52,
        "dist_from_52w_high_pct": (round((last["close"] / hi52 - 1) * 100, 1)
                                   if hi52 else None),
        "change_5d_pct": chg_5d,
        "change_10d_pct": chg_10d,
        "last_5_closes": [round(c, 2) for c in closes[-5:]],
    }
    if position:
        facts["position"] = position
    if plan:
        facts["plan"] = plan
    # Analyst/fundamental fields are NOT auto-filled — mark missing
    facts["analyst_rating"] = "[数据缺失:需手动查]"
    facts["analyst_target"] = "[数据缺失:需手动查]"
    facts["pe_ttm"] = "[数据缺失:需手动查]"

    return {
        "preamble": ("Technical snapshot for %s. Use these numbers, not "
                     "training-data memory. Fields marked [数据缺失] need "
                     "manual lookup." % ticker),
        "facts": facts,
        "as_of": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--position", default="")
    ap.add_argument("--plan", default="")
    ap.add_argument("-o", "--output", default=None)
    a = ap.parse_args()
    ctx = build(a.ticker.upper(), a.position, a.plan)
    out = json.dumps(ctx, ensure_ascii=False, indent=1)
    if a.output:
        open(a.output, "w").write(out)
        print("wrote %s" % a.output, file=sys.stderr)
    else:
        print(out)


if __name__ == "__main__":
    main()
