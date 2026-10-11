#!/usr/bin/env python3
"""Stock-analysis probe runner (muse-thinktank eval).

Runs each model over the question set, with retries on 429/empty,
a weekly $5 spend ledger (fail-closed for paid calls), a per-model
spend cap (--per-model-cap, default $0.50, D12: stop the model when
the worst-case estimate would breach it), and a fail streak stop
(D12: 2 consecutive failed questions stop the model — "两次失败就停").
Failed/empty calls are billed by their actual usage.cost (D12 ledger
fix), and raw answers are saved under docs/eval/stock/raw/<date>/.

Usage:
    OPENROUTER_API_KEY=... run_stock.py \
        --models m1,m2 --questions docs/eval/stock/questions-v1.json \
        --out-dir docs/eval/stock/raw/2026-10-11 \
        [--prices '{"model": {"input": 0.27, "output": 1.10}}'] \
        [--max-tokens 1000] [--retries 3] [--per-model-cap 0.50]

Scoring is manual (see questions-v1.md rubric); this script only collects.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://openrouter.ai/api/v1/chat/completions"
WEEKLY_CAP = 5.0
# D12 (2026-10-11, qwen $1.30 复盘)：单模型费用上限——病态重试/重度 reasoning
# 模型在单题烧钱时尽早熔断。fail-closed，可通过 --per-model-cap 调整。
PER_MODEL_CAP = 0.50
# D12：同一模型连续失败达到此次数后，停止该模型剩余题目（"两次失败就停"）。
FAIL_STREAK_STOP = 2
SYSTEM = ("你是实战派股票交易顾问。只给具体、可执行的建议：明确的价位、比例、"
          "股数、止损位。不说套话，不预测涨跌只谈应对。")


def log(msg):
    print("[eval] " + msg, file=sys.stderr, flush=True)


def week_key():
    d = dt.date.today()
    iso = d.isocalendar()
    return "%d-W%02d" % (iso[0], iso[1])


def load_ledger(path):
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except (ValueError, OSError):
            pass
    return {"weeks": {}}


def save_ledger(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def ledger_spent(data):
    w = data["weeks"].get(week_key(), {})
    return float(w.get("spent", 0.0))


def ledger_spent_model(data, model):
    """本周该模型已花。ledger 跨 runner 共用，run_stock/run_code 累计。"""
    w = data["weeks"].get(week_key(), {})
    return round(sum(float(e.get("cost", 0.0))
                     for e in w.get("entries", [])
                     if e.get("model") == model), 6)


def ledger_add(data, model, qid, cost):
    w = data["weeks"].setdefault(
        week_key(), {"cap": WEEKLY_CAP, "spent": 0.0, "entries": []})
    w["spent"] = round(w["spent"] + cost, 6)
    w["entries"].append({"ts": dt.datetime.now(dt.timezone.utc).isoformat(),
                         "model": model, "qid": qid, "cost": cost})


def chat(model, prompt, max_tokens, timeout, key):
    payload = {"model": model,
               "messages": [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": prompt}],
               "max_tokens": max_tokens, "temperature": 0.5}
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": "muse-thinktank-eval/0.1",
                 "Authorization": "Bearer " + key})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")[:200]
        except Exception:
            body = ""
        return {"text": "", "cost": 0.0, "tokens": 0,
                "error": "HTTP %d: %s" % (exc.code, body),
                "retryable": exc.code == 429,
                "elapsed": time.time() - t0}
    except Exception as exc:
        return {"text": "", "cost": 0.0, "tokens": 0,
                "error": "network: %s" % exc, "retryable": True,
                "elapsed": time.time() - t0}
    err = data.get("error")
    usage = data.get("usage") or {}
    try:
        cost = float(usage.get("cost") or 0)
    except (ValueError, TypeError):
        cost = 0.0
    tokens = usage.get("total_tokens", 0)
    # D12: 失败/空返回的调用也消耗了 token —— 按 usage.cost 如实记账，
    # 否则 ledger 永远对不上服务端的实际扣费（第三批实测 ledger $3.86 vs 实际 $5.65）。
    if err:
        return {"text": "", "cost": cost, "tokens": tokens,
                "error": "API: %s" % json.dumps(err)[:200],
                "retryable": False, "elapsed": time.time() - t0}
    ch = (data.get("choices") or [{}])[0]
    text = ((ch.get("message") or {}).get("content") or "").strip()
    return {"text": text, "cost": cost,
            "tokens": tokens,
            "error": None, "retryable": False,
            "elapsed": time.time() - t0}


def safe_name(s):
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True)
    ap.add_argument("--questions", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--prices", default="{}")
    ap.add_argument("--max-tokens", type=int, default=1000)
    ap.add_argument("--max-tokens-map", default="{}")
    ap.add_argument("--ledger-path", default=None)
    ap.add_argument("--per-model-cap", type=float, default=PER_MODEL_CAP,
                    help="单模型本周费用上限（默认 $%.2f），超限即停该模型"
                    % PER_MODEL_CAP)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=150)
    a = ap.parse_args()
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        print("error: OPENROUTER_API_KEY is not set", file=sys.stderr)
        raise SystemExit(2)
    prices = json.loads(a.prices)
    mt_map = json.loads(a.max_tokens_map)
    questions = json.load(open(a.questions))["questions"]
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    os.makedirs(a.out_dir, exist_ok=True)
    ledger_path = a.ledger_path or os.path.join(os.path.dirname(a.out_dir),
                                                "ledger.json")
    ledger = load_ledger(ledger_path)
    summary = {"date": dt.date.today().isoformat(), "results": []}

    for model in models:
        mt = mt_map.get(model, a.max_tokens)
        paid = not model.endswith(":free")
        model_spent = ledger_spent_model(ledger, model)  # 本周该模型已花（含其他 runner）
        fail_streak = 0
        model_stop = None  # 提前停止该模型的原因（per-model cap / fail streak）
        for q in questions:
            qid = q["id"]
            if model_stop:
                summary["results"].append(
                    {"model": model, "qid": qid, "status": "skipped",
                     "reason": model_stop})
                continue
            est_cost = 0.0
            if paid:
                p = prices.get(model)
                if not p:
                    log("SKIP %s %s: 缺价格表（ledger fail-closed）" % (model, qid))
                    summary["results"].append(
                        {"model": model, "qid": qid, "status": "skipped",
                         "reason": "no price"})
                    continue
                est_cost = ((len(q["prompt"]) + len(SYSTEM)) / 4.0 / 1e6
                             * float(p["input"])
                             + mt / 1e6 * float(p["output"]))
                if ledger_spent(ledger) + est_cost > WEEKLY_CAP:
                    log("SKIP %s %s: 周限额 $%.2f 将超（已花 $%.4f）"
                        % (model, qid, WEEKLY_CAP, ledger_spent(ledger)))
                    summary["results"].append(
                        {"model": model, "qid": qid, "status": "skipped",
                         "reason": "weekly cap"})
                    continue
                if model_spent + est_cost > a.per_model_cap:
                    # D12: 单模型上限（最坏估计），fail-closed，停该模型不殃及他模
                    log("STOP %s: 单模型上限 $%.2f 将超（该模型本周已花 $%.4f）"
                        % (model, a.per_model_cap, model_spent))
                    model_stop = "per-model cap"
                    summary["results"].append(
                        {"model": model, "qid": qid, "status": "skipped",
                         "reason": model_stop})
                    continue
            # call with retries
            result, attempt = None, 0
            while attempt <= a.retries:
                attempt += 1
                result = chat(model, q["prompt"], mt,
                              a.timeout, key)
                if result["error"] is None and result["text"]:
                    break
                if not result["retryable"] and result["error"] \
                        and "429" not in result["error"]:
                    # empty response is retryable once more
                    if not result["text"] and attempt <= a.retries:
                        log("  %s %s 空返回，重试 %d/%d"
                            % (model, qid, attempt, a.retries))
                        time.sleep(10)
                        continue
                    break
                wait = 15 * attempt
                log("  %s %s 可重试错误（%s），%ds 后重试 %d/%d"
                    % (model, qid, result["error"], wait,
                       attempt, a.retries))
                time.sleep(wait)
            ok = result["error"] is None and bool(result["text"])
            reason = result["error"] or "empty response"
            # D12: 失败/空返回也按实际 usage.cost 记账（之前记 $0 是已知 bug）
            cost = result["cost"]
            ledger_add(ledger, model, qid, cost)
            save_ledger(ledger_path, ledger)
            if paid:
                model_spent = round(model_spent + cost, 6)
            if ok:
                fail_streak = 0
            else:
                # D12: 两次失败就停——连续失败说明模型当下不可用，别拿钱续命
                fail_streak += 1
                if fail_streak >= FAIL_STREAK_STOP:
                    log("STOP %s: 连续 %d 题失败，停止该模型剩余题目"
                        % (model, fail_streak))
                    model_stop = "fail streak"
            fname = "%s__%s.md" % (safe_name(model), qid)
            with open(os.path.join(a.out_dir, fname), "w") as f:
                f.write("# %s · %s\n\n" % (model, q["title"]))
                f.write("- 日期：%s\n- tokens：%s\n- 费用：$%.6f\n"
                        "- 尝试次数：%d\n- 状态：%s\n\n---\n\n"
                        % (dt.date.today().isoformat(), result["tokens"],
                           cost, attempt,
                           "ok" if ok else "FAIL: " + reason))
                f.write(result["text"] if ok else
                        "> FAIL: %s\n" % reason)
            summary["results"].append(
                {"model": model, "qid": qid,
                 "status": "ok" if ok else "fail",
                 "file": fname, "tokens": result["tokens"],
                 "cost": cost,
                 "attempts": attempt,
                 "error": reason if not ok else None})
            log("%s %s: %s (%.1fs, %s tokens, $%.6f, 尝试 %d) [本周期已花 $%.4f]"
                % (model, qid, "ok" if ok else "FAIL: " + reason,
                   result["elapsed"],
                   result["tokens"], cost,
                   attempt, ledger_spent(ledger)))
    with open(os.path.join(a.out_dir, "_summary.json"), "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    log("完成。本周 ledger 已花 $%.4f / $%.2f" % (ledger_spent(ledger), WEEKLY_CAP))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
