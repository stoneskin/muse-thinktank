#!/usr/bin/env python3
"""Code/design probe runner (muse-thinktank eval).

Same harness as run_stock.py (retries, weekly $5 ledger, per-model cap,
fail-streak stop, failed calls billed by actual usage.cost — see D12 in
run_stock.py), plus: for P1 answers, extracts the first ```python block
and runs the hidden TTLCache tests, recording pass counts.

Usage:
    OPENROUTER_API_KEY=... run_code.py \
        --models m1,m2 --questions docs/eval/code/questions-v1.json \
        --out-dir docs/eval/code/raw/2026-10-11 \
        --ledger-path docs/eval/stock/raw/ledger.json \
        [--prices '{...}'] [--max-tokens 2500]
        [--max-tokens-map '{"model": 6000}'] [--retries 2]
        [--per-model-cap 0.50]

P2/P3 are scored manually; this script only collects (+ auto P1 tests).
"""
import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_stock as rs

CODE_SYSTEM = ("你是一位资深软件工程师。直接回答用户当次提出的问题："
               "代码实现题只交实现代码（类名 TTLCache，放在 ```python 代码块里）；"
               "代码评审题逐个指出 bug 的位置、触发条件和修复；"
               "架构设计题给整体方案、关键权衡和最大风险。"
               "不要回答用户没问的题目。不说套话。")

CODE_BLOCK = re.compile(r"```python\s*\n(.*?)```", re.S)


def run_p1_tests(code_text, tests_path):
    """Extract first python block, run hidden tests. Returns (passed, total, error)."""
    m = CODE_BLOCK.search(code_text)
    if not m:
        return 0, 0, "no python code block found"
    tmpd = tempfile.mkdtemp(prefix="p1eval_")
    impl_path = os.path.join(tmpd, "ttl_cache_impl.py")
    with open(impl_path, "w") as f:
        f.write(m.group(1))
    try:
        spec = importlib.util.spec_from_file_location("ttl_cache_impl", impl_path)
        impl = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(impl)
        if not hasattr(impl, "TTLCache"):
            return 0, 0, "TTLCache class not defined"
        tspec = importlib.util.spec_from_file_location("test_ttl_cache", tests_path)
        tmod = importlib.util.module_from_spec(tspec)
        tspec.loader.exec_module(tmod)
        tmod.TTLCache = impl.TTLCache
        passed, total, first_err = 0, 0, None
        for t in tmod.TESTS:
            total += 1
            try:
                t()
                passed += 1
            except Exception as e:  # noqa: BLE001 - test harness
                if first_err is None:
                    first_err = "%s: %s" % (t.__name__, repr(e)[:120])
        return passed, total, first_err
    except Exception as e:  # noqa: BLE001
        return 0, 0, "exec error: %s" % repr(e)[:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True)
    ap.add_argument("--questions", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--ledger-path", required=True)
    ap.add_argument("--prices", default="{}")
    ap.add_argument("--max-tokens", type=int, default=2500)
    ap.add_argument("--max-tokens-map", default="{}")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--per-model-cap", type=float, default=rs.PER_MODEL_CAP,
                    help="单模型本周费用上限（默认 $%.2f），超限即停该模型"
                    % rs.PER_MODEL_CAP)
    ap.add_argument("--timeout", type=float, default=180)
    a = ap.parse_args()
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        print("error: OPENROUTER_API_KEY is not set", file=sys.stderr)
        raise SystemExit(2)
    rs.SYSTEM = CODE_SYSTEM
    prices = json.loads(a.prices)
    mt_map = json.loads(a.max_tokens_map)
    questions = json.load(open(a.questions))["questions"]
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    os.makedirs(a.out_dir, exist_ok=True)
    ledger = rs.load_ledger(a.ledger_path)
    summary = {"date": dt.date.today().isoformat(), "results": []}
    tests_path = os.path.join(os.path.dirname(a.questions), "test_ttl_cache.py")
    if not os.path.exists(tests_path):
        tests_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "test_ttl_cache.py")

    for model in models:
        mt = mt_map.get(model, a.max_tokens)
        paid = not model.endswith(":free")
        model_spent = rs.ledger_spent_model(ledger, model)
        fail_streak = 0
        model_stop = None  # D12: 提前停止该模型的原因
        for q in questions:
            qid = q["id"]
            if model_stop:
                summary["results"].append(
                    {"model": model, "qid": qid, "status": "skipped",
                     "reason": model_stop})
                continue
            if paid:
                p = prices.get(model)
                if not p:
                    rs.log("SKIP %s %s: 缺价格表（ledger fail-closed）" % (model, qid))
                    summary["results"].append(
                        {"model": model, "qid": qid, "status": "skipped",
                         "reason": "no price"})
                    continue
                est_cost = ((len(q["prompt"]) + len(rs.SYSTEM)) / 4.0 / 1e6
                            * float(p["input"]) + mt / 1e6 * float(p["output"]))
                if rs.ledger_spent(ledger) + est_cost > rs.WEEKLY_CAP:
                    rs.log("SKIP %s %s: 周限额将超（已花 $%.4f）"
                           % (model, qid, rs.ledger_spent(ledger)))
                    summary["results"].append(
                        {"model": model, "qid": qid, "status": "skipped",
                         "reason": "weekly cap"})
                    continue
                if model_spent + est_cost > a.per_model_cap:
                    # D12: 单模型上限（最坏估计），fail-closed，停该模型不殃及他模
                    rs.log("STOP %s: 单模型上限 $%.2f 将超（该模型本周已花 $%.4f）"
                           % (model, a.per_model_cap, model_spent))
                    model_stop = "per-model cap"
                    summary["results"].append(
                        {"model": model, "qid": qid, "status": "skipped",
                         "reason": model_stop})
                    continue
            result, attempt = None, 0
            while attempt <= a.retries:
                attempt += 1
                result = rs.chat(model, q["prompt"], mt, a.timeout, key)
                if result["error"] is None and result["text"]:
                    break
                if not result["retryable"] and result["error"] \
                        and "429" not in result["error"]:
                    if not result["text"] and attempt <= a.retries:
                        rs.log("  %s %s 空返回，重试 %d/%d"
                               % (model, qid, attempt, a.retries))
                        time.sleep(10)
                        continue
                    break
                wait = 15 * attempt
                rs.log("  %s %s 可重试错误（%s），%ds 后重试 %d/%d"
                       % (model, qid, result["error"], wait, attempt, a.retries))
                time.sleep(wait)
            ok = result["error"] is None and bool(result["text"])
            reason = result["error"] or "empty response"
            # D12: 失败/空返回也按实际 usage.cost 记账（之前记 $0 是已知 bug）
            cost = result["cost"]
            # P1 auto-tests
            p1 = None
            if ok and qid == "P1":
                passed, total, err = run_p1_tests(result["text"], tests_path)
                p1 = {"passed": passed, "total": total, "error": err}
            rs.ledger_add(ledger, model, qid, cost)
            rs.save_ledger(a.ledger_path, ledger)
            if paid:
                model_spent = round(model_spent + cost, 6)
            if ok:
                fail_streak = 0
            else:
                # D12: 两次失败就停——连续失败说明模型当下不可用，别拿钱续命
                fail_streak += 1
                if fail_streak >= rs.FAIL_STREAK_STOP:
                    rs.log("STOP %s: 连续 %d 题失败，停止该模型剩余题目"
                           % (model, fail_streak))
                    model_stop = "fail streak"
            fname = "%s__%s.md" % (rs.safe_name(model), qid)
            with open(os.path.join(a.out_dir, fname), "w") as f:
                f.write("# %s · %s\n\n" % (model, q["title"]))
                f.write("- 日期：%s\n- tokens：%s\n- 费用：$%.6f\n"
                        "- 尝试次数：%d\n- 状态：%s\n"
                        % (dt.date.today().isoformat(), result["tokens"],
                           cost, attempt, "ok" if ok else "FAIL: " + reason))
                if p1 is not None:
                    f.write("- P1 自动测试：%d/%d 通过%s\n"
                            % (p1["passed"], p1["total"],
                               ("（首错：%s）" % p1["error"]) if p1["error"] else ""))
                f.write("\n---\n\n")
                f.write(result["text"] if ok else "> FAIL: %s\n" % reason)
            summary["results"].append(
                {"model": model, "qid": qid,
                 "status": "ok" if ok else "fail",
                 "file": fname, "tokens": result["tokens"],
                 "cost": cost, "attempts": attempt,
                 "p1_tests": p1,
                 "error": reason if not ok else None})
            rs.log("%s %s: %s (%.1fs, %s tokens, $%.6f, 尝试 %d%s) [已花 $%.4f]"
                   % (model, qid, "ok" if ok else "FAIL: " + reason,
                      result["elapsed"], result["tokens"], cost, attempt,
                      ("; P1 %d/%d" % (p1["passed"], p1["total"])
                       if p1 else ""),
                      rs.ledger_spent(ledger)))
    with open(os.path.join(a.out_dir, "_summary.json"), "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    rs.log("完成。本周 ledger 已花 $%.4f / $%.2f"
           % (rs.ledger_spent(ledger), rs.WEEKLY_CAP))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
