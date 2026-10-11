"""muse-thinktank v0.4 -- multi-model deliberation orchestrator.

CLI entry point. Core logic lives in the tt/ package.
"""

import argparse
import concurrent.futures as cf
import json
import os
import sys
import time

# tt/ package lives alongside this file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tt.util import log
from tt.transport import api_key, chat, health_check, free_ids, resolve_free
from tt.contracts import (
    extract_json, validate_judge, normalize_judge, judge_needs_human,
    judges_agree, disagreement_entropy,
    JUDGE_SYSTEM, JUDGE_TEMPLATE, SYNTH_SYSTEM, SYNTH_TEMPLATE,
)
from tt.budget import BudgetExceeded, RuntimeBudget, load_prices, worst_case_cost
from tt.context import (
    PANEL_SYSTEM, load_context_data, sanitize_context, build_panel_prompt,
)
from tt.members import (
    load_member_state, save_member_state, record_member, record_judge,
    availability, load_capability_scores, select_members,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["ask"])
    ap.add_argument("--models", required=True,
                    help="comma-separated exact OpenRouter model ids")
    ap.add_argument("--judge-model", required=True)
    ap.add_argument("--judge-model2", default=None,
                    help="v0.3a: second judge for cross-validation; "
                         "disagreement escalates to human")
    ap.add_argument("--member-state", default=None,
                    help="v0.3a: JSON file for sliding-window member stats "
                         "(availability tracking)")
    ap.add_argument("--capability-scores", default=None,
                    help="v0.3a: JSON {model: 0.0-1.0} capability scores; "
                         "missing model defaults to 1.0")
    ap.add_argument("--context-data", default=None,
                    help="v0.3b: JSON file with real-time data to inject into "
                         "panel prompts. Format: {\"preamble\": \"...\", "
                         "\"facts\": {\"key\": \"value\"}}. Injected after "
                         "the question with a [实时数据] marker.")
    ap.add_argument("--synth-model", default=None,
                    help="default: same as --judge-model")
    ap.add_argument("--show-all", action="store_true",
                    help="print every answer + judge recommendation; human judges")
    ap.add_argument("--verdict", action="store_true",
                    help="judge picks winner; print winner's answer as-is")
    ap.add_argument("--budget", type=float, default=2.0,
                    help="USD; abort remaining calls when exceeded")
    ap.add_argument("--panel-timeout", type=float, default=120)
    ap.add_argument("--max-tokens", type=int, default=800)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--free-only", action="store_true",
                    help="fail-closed free-id resolution for panel models")
    ap.add_argument("--free-state", default=None,
                    help="models.py scan report for --free-only")
    ap.add_argument("--estimate", action="store_true",
                    help="print run plan (calls, worst-case tokens/cost/time) "
                         "and exit without calling any API")
    ap.add_argument("--prices", default=None,
                    help="JSON string or file: {model: {input, output}} "
                         "$/1M tokens, for worst-path cost estimate")
    ap.add_argument("--no-health-check", action="store_true",
                    help="skip the pre-panel lightweight ping")
    ap.add_argument("question", help="the question to deliberate")
    a = ap.parse_args()

    models = [m.strip() for m in a.models.split(",") if m.strip()]
    free_set = set()
    if a.free_only:
        free_set = free_ids(a.free_state)
        models = [resolve_free(m, free_set) for m in models]
        log("free-only: %d models resolved against free pool" % len(models))
    synth_model = a.synth_model or a.judge_model

    # ---- pre-run worst-path cost check (fail-closed for money) ----
    prices = load_prices(a.prices)
    judge_models = [a.judge_model] + ([a.judge_model2] if a.judge_model2 else [])
    worst, missing = worst_case_cost(models, judge_models, synth_model,
                                     a.question, a.max_tokens, prices,
                                     free_set)

    if a.estimate:
        n_judges = 2 if a.judge_model2 else 1
        n_calls = len(models) + n_judges + 1  # panel + judges + synth
        worst_comp = (len(models) * a.max_tokens
                      + n_judges * max(900, a.max_tokens)
                      + max(1200, a.max_tokens))
        judges_str = a.judge_model + (" + " + a.judge_model2
                                      if a.judge_model2 else "")
        print("智囊团运行预估（最坏路径，v0.3a）：")
        print("  模型：%s" % ", ".join(models))
        print("  judge：%s  synth：%s" % (judges_str, synth_model))
        print("  API 调用：%d（panel %d + judge %d + synth 1）"
              % (n_calls, len(models), n_judges))
        print("  completion tokens 上限：%d" % worst_comp)
        if worst is None:
            print("  费用上限：无法预估（缺 %s 的价格，用 --prices 提供）"
                  % missing)
        else:
            print("  费用上限：$%.4f（预算 $%.2f）" % (worst, a.budget))
        worst_secs = a.panel_timeout * 3
        print("  耗时：最长约 %.0f 分钟（超时上限），通常 1-3 分钟"
              % (worst_secs / 60))
        print("回复 去=开工，改=调整模型/预算。")
        return 0

    if worst is None:
        print("error: 无法预估 %s 的费用（缺价格表），拒绝启动。"
              "用 --prices 提供 {model: {input, output}}（$/1M tokens）。"
              % missing, file=sys.stderr)
        raise SystemExit(2)
    if worst > a.budget:
        print("error: 最坏路径费用 $%.4f 超过预算 $%.2f，拒绝启动。"
              % (worst, a.budget), file=sys.stderr)
        raise SystemExit(3)
    log("最坏路径费用 $%.4f ≤ 预算 $%.2f，通过" % (worst, a.budget))

    key = api_key()
    spent = 0.0
    t_start = time.time()
    # v0.4: runtime budget熔断器（线程安全，每次API调用后charge）
    runtime_budget = RuntimeBudget(a.budget)

    # ---- v0.3a: dynamic member selection ----
    member_state = load_member_state(a.member_state)
    cap_scores = load_capability_scores(a.capability_scores)
    if a.member_state or a.capability_scores:
        models, dropped = select_members(models, member_state, cap_scores)
        if not models:
            log("fail-closed: 动态成员选择剔除了所有模型")
            raise SystemExit(2)

    # ---- pre-panel health check ----
    if not a.no_health_check:
        models, hc_spent = health_check(models, key)
        spent += hc_spent
        if not models:
            log("fail-closed: 所有模型健康检测失败，拒绝空跑")
            raise SystemExit(2)
        log("health-check 通过 %d 个模型" % len(models))

    # ---- v0.3b: load real-time context data ----
    ctx_data = load_context_data(a.context_data)
    if ctx_data:
        log("实时数据注入：%d 个事实" % len(ctx_data.get("facts", {})))
    panel_question = build_panel_prompt(a.question, ctx_data)
    panel_system = PANEL_SYSTEM if ctx_data else None

    # ---- phase 1: panel ----
    log("phase 1/3 panel: %d models, timeout %gs"
        % (len(models), a.panel_timeout))
    answers = []

    def run_one(idx, model):
        msgs = [{"role": "user", "content": panel_question}]
        if panel_system:
            msgs.insert(0, {"role": "system", "content": panel_system})
        r = chat(model, msgs,
                 a.max_tokens, a.temperature, a.panel_timeout, key)
        return idx, model, r

    # v0.4: global timeout — a stuck panel model can't deadlock the run.
    panel_timeout = a.panel_timeout + 30
    with cf.ThreadPoolExecutor(max_workers=len(models)) as ex:
        futs = {ex.submit(run_one, i, m): (i, m)
                for i, m in enumerate(models)}
        done_futs, pending = cf.wait(futs, timeout=panel_timeout,
                                     return_when=cf.ALL_COMPLETED)
        for fut in pending:
            i, m = futs[fut]
            log("[%d/%d] %s 超时（%.0fs），记失败" % (i + 1, len(models), m,
                                                     panel_timeout))
            fut.cancel()
        done = 0
        for fut in futs:
            i, m = futs[fut]
            if fut in pending:
                answers.append({"model": m, "text": "", "ok": False,
                                "error": "timeout", "truncated": False})
                done += 1
                continue
            try:
                idx, model, r = fut.result(timeout=0)
            except Exception as exc:
                model = m
                r = {"text": "", "cost": 0.0,
                     "error": "worker: %s" % exc, "elapsed": 0}
            done += 1
            spent += r["cost"]
            # v0.4: runtime budget熔断
            try:
                runtime_budget.charge(r["cost"])
            except BudgetExceeded as be:
                log("BUDGET熔断：%s -- aborting" % be)
                raise SystemExit(3)
            if r["error"] or not r["text"]:
                reason = r["error"] or "empty response"
                log("[%d/%d] %s FAIL: %s" % (done, len(models), model, reason))
                answers.append({"model": model, "text": "",
                                "ok": False, "error": reason,
                                "truncated": False})
            else:
                ntok = (r["usage"] or {}).get("total_tokens", "?")
                trunc = " [输出被截断]" if r["truncated"] else ""
                log("[%d/%d] %s ok (%.1fs, %s tokens, $%.4f)%s"
                    % (done, len(models), model, r["elapsed"], ntok,
                       r["cost"], trunc))
                answers.append({"model": model, "text": r["text"],
                                "ok": True, "error": None,
                                "truncated": r["truncated"]})
    answers.sort(key=lambda x: models.index(x["model"]))
    ok_answers = [x for x in answers if x["ok"]]
    phase1_elapsed = time.time() - t_start
    log("phase 1 done in %.1fs -- %d/%d ok, spent $%.4f"
        % (phase1_elapsed, len(ok_answers), len(models), spent))
    # v0.3a: record member performance
    if a.member_state:
        for x in answers:
            # latency not tracked per-answer in v0.2; use phase avg
            record_member(member_state, x["model"], x["ok"],
                          phase1_elapsed / max(len(models), 1))
    if spent > a.budget:
        log("budget $%.2f exceeded after panel -- aborting" % a.budget)
        raise SystemExit(3)
    if not ok_answers:
        log("fail-closed: no usable answer from panel -- refusing to synthesize")
        raise SystemExit(2)
    log("预计 judge + synth 还需约 %.0fs" % phase1_elapsed)

    # ---- phase 2: judge (v0.3a: dual-judge cross-validation) ----
    t1 = time.time()
    judges = [a.judge_model] + ([a.judge_model2] if a.judge_model2 else [])
    log("phase 2/3 judge: %s" % " + ".join(judges))
    ans_block = "\n\n".join(
        "【回答%d · %s】%s\n%s" % (i, x["model"],
                                  "（⚠ 输出被截断）" if x["truncated"] else "",
                                  x["text"])
        for i, x in enumerate(ok_answers))

    def run_judge(jm):
        jr = chat(jm,
                  [{"role": "system", "content": JUDGE_SYSTEM},
                   {"role": "user",
                    "content": JUDGE_TEMPLATE.format(n=len(ok_answers),
                                                     answers=ans_block)}],
                  max(900, a.max_tokens), 0.3, a.panel_timeout, key)
        raw = extract_json(jr["text"]) if not jr["error"] else None
        j = normalize_judge(raw, len(ok_answers)) \
            if raw is not None else None
        # v0.3a: track judge bias stats
        if j is not None and a.member_state:
            n_acc = sum(1 for d in j["decisions"]
                        if d["verdict"] == "accept")
            n_rej = sum(1 for d in j["decisions"]
                        if d["verdict"] == "reject")
            record_judge(member_state, jm, n_acc, n_rej)
        return jm, jr, j

    judge_results = {}
    # v0.4: global timeout for judges — a stuck judge can't deadlock the run.
    # wait() with timeout, cancel pending, degrade missing results.
    judge_timeout = a.panel_timeout + 30
    with cf.ThreadPoolExecutor(max_workers=len(judges)) as ex:
        futs = {ex.submit(run_judge, jm): jm for jm in judges}
        done, pending = cf.wait(futs, timeout=judge_timeout,
                                return_when=cf.ALL_COMPLETED)
        for fut in pending:
            jm = futs[fut]
            log("judge %s 超时（%.0fs），降级跳过" % (jm, judge_timeout))
            fut.cancel()
        for fut in futs:
            jm = futs[fut]
            if fut in pending:
                judge_results[jm] = ({"cost": 0, "error": "timeout"}, None)
                continue
            try:
                jm2, jr, j = fut.result(timeout=0)
            except Exception as exc:
                log("judge %s 异常：%s" % (jm, exc))
                judge_results[jm] = ({"cost": 0, "error": str(exc)}, None)
                continue
            spent += jr["cost"]
            # v0.4: runtime budget熔断
            if runtime_budget:
                try:
                    runtime_budget.charge(jr["cost"])
                except BudgetExceeded as be:
                    log("BUDGET熔断：%s -- aborting" % be)
                    raise SystemExit(3)
            judge_results[jm] = (jr, j)
            if j is None:
                log("judge %s 输出无效（%s）" % (jm, jr["error"] or "违反契约"))
            else:
                log("judge %s: winner=%s confidence=%s"
                    % (jm, j.get("winner"), j.get("confidence")))

    # v0.3a: cross-validation
    judge_list = [judge_results[jm][1] for jm in judges]
    judge = judge_list[0]
    dual_ok, dual_reason = True, ""
    if len(judges) == 2:
        dual_ok, dual_reason = judges_agree(judge_list[0], judge_list[1],
                                            len(ok_answers))
        if dual_ok:
            log("双 judge 一致，通过")
        else:
            log("双 judge 分歧（%s）→ 升级人终审" % dual_reason)
            judge = None  # force show-all path
    # v0.3a: disagreement entropy (convergence scaffold)
    entropy = disagreement_entropy(judge, len(ok_answers))
    log("phase 2 done in %.1fs -- entropy=%.1f (spent $%.4f)"
        % (time.time() - t1, entropy, spent))
    if spent > a.budget:
        log("budget $%.2f exceeded after judge -- aborting" % a.budget)
        raise SystemExit(3)

    # ---- phase 3 ----
    t2 = time.time()
    need_human = judge is None or judge_needs_human(judge)
    if a.show_all or need_human:
        out = []
        for i, x in enumerate(ok_answers):
            out.append("===== 回答%d · %s =====" % (i, x["model"]))
            out.append(x["text"])
        if judge is not None:
            out.append("===== judge 推荐 =====")
            dec_str = "; ".join(
                "#%d %s/%s" % (d["id"], d["verdict"], d["severity"])
                for d in judge["decisions"])
            out.append("winner: %s（%s）\ndecisions: %s"
                       % (judge.get("winner"),
                          judge.get("rationale") or "", dec_str))
            out.append("由人终审：请回复选中的编号。")
        print("\n\n".join(out))
        # v0.3a: persist member stats (also on human-verdict path)
        if a.member_state:
            save_member_state(a.member_state, member_state)
        log("phase 3 done in %.1fs -- awaiting human verdict "
            "(total %.1fs, spent $%.4f)"
            % (time.time() - t2, time.time() - t_start, spent))
        return 0

    rej = {d["id"] for d in judge["decisions"]
           if d["verdict"] == "reject"}
    usable = [x for i, x in enumerate(ok_answers) if i not in rej]
    if not usable:
        log("fail-closed: judge rejected everything -- no usable answer")
        raise SystemExit(2)

    if a.verdict:
        w = judge.get("winner")
        if isinstance(w, int) and 0 <= w < len(ok_answers) and w not in rej:
            print(ok_answers[w]["text"])
        else:
            log("judge 无明确 winner，退回并列展示")
            for i, x in enumerate(usable):
                print("===== 回答%d · %s =====\n%s\n"
                      % (i, x["model"], x["text"]))
        log("done in %.1fs, spent $%.4f" % (time.time() - t_start, spent))
        return 0

    log("phase 3/3 synth: %s" % synth_model)
    judge_for_synth = dict(judge)
    judge_for_synth["decisions"] = [d for d in judge["decisions"]
                                    if d["severity"] != "nitpick"]
    sr = chat(synth_model,
              [{"role": "system", "content": SYNTH_SYSTEM},
               {"role": "user",
                "content": SYNTH_TEMPLATE.format(
                    judge=json.dumps(judge_for_synth, ensure_ascii=False,
                                     indent=2),
                    answers=ans_block)}],
              max(1200, a.max_tokens), 0.5, a.panel_timeout, key)
    spent += sr["cost"]
    if sr["error"] or not sr["text"]:
        log("synth failed (%s) → 降级并列展示" % (sr["error"] or "empty"))
        for i, x in enumerate(usable):
            print("===== 回答%d · %s =====\n%s\n"
                  % (i, x["model"], x["text"]))
    else:
        print(sr["text"])
    # v0.3a: persist member stats
    if a.member_state:
        save_member_state(a.member_state, member_state)
        log("成员状态已保存（%d 个模型）" % len(member_state))
    log("done in %.1fs, spent $%.4f" % (time.time() - t_start, spent))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

