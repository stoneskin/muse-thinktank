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
from tt.transport import api_key, chat, health_check, free_ids, resolve_free, fetch_pr_diff
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
    ap.add_argument("--allow-judge-overlap", action="store_true",
                    help="v0.4: allow judge model(s) to also be panel members "
                         "(default: fail-closed; answers are anonymized "
                         "for judges either way)")
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
                         "the question with a [real-time data] marker.")
    ap.add_argument("--pr-diff", default=None,
                    help="v0.4: GitHub PR URL "
                         "(https://github.com/{owner}/{repo}/pull/{n}); "
                         "fetches the public diff and injects it into the "
                         "panel prompt for code review")
    ap.add_argument("--synth-model", default=None,
                    help="default: same as --judge-model")
    ap.add_argument("--show-all", action="store_true",
                    help="print every answer + judge recommendation; human judges")
    ap.add_argument("--verdict", action="store_true",
                    help="judge picks winner; print winner's answer as-is")
    ap.add_argument("--budget", type=float, default=2.0,
                    help="USD; abort remaining calls when exceeded")
    ap.add_argument("--budget-headroom", type=float, default=1.1,
                    help="v0.4: runtime budget aborts at budget * headroom "
                         "(default 1.1)")
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

    # v0.4: fail-closed on judge/panel overlap (self-preference bias).
    # A judge must not deliberate and judge the same question.
    judge_models = [a.judge_model] + ([a.judge_model2] if a.judge_model2 else [])
    overlap = [jm for jm in judge_models if jm in models]
    if overlap and not a.allow_judge_overlap:
        print("error: judge model(s) %s also in --models panel. "
              "A judge cannot judge its own deliberation (self-preference "
              "bias). Use a different --judge-model, or pass "
              "--allow-judge-overlap to proceed anyway (answers stay "
              "anonymized for judges)." % ", ".join(overlap))
        raise SystemExit(2)

    # ---- pre-run worst-path cost check (fail-closed for money) ----
    prices = load_prices(a.prices)
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
        print("Thinktank run estimate (worst path, v0.4):")
        print("  models: %s" % ", ".join(models))
        print("  judge: %s  synth: %s" % (judges_str, synth_model))
        print("  API calls: %d (panel %d + judge %d + synth 1)"
              % (n_calls, len(models), n_judges))
        print("  completion tokens cap: %d" % worst_comp)
        if worst is None:
            print("  cost cap: cannot estimate (missing price for %s, provide via --prices)"
                  % missing)
        else:
            print("  cost cap: $%.4f (budget $%.2f)" % (worst, a.budget))
        worst_secs = a.panel_timeout * 3
        print("  time: up to ~%.0f min (timeout cap), typically 1-3 min"
              % (worst_secs / 60))
        print("Reply go=start, change=adjust models/budget.")
        return 0

    if worst is None:
        print("error: cannot estimate cost for %s (no price table), refusing to start."
              "Provide via --prices {model: {input, output}} ($/1M tokens)."
              % missing, file=sys.stderr)
        raise SystemExit(2)
    if worst > a.budget:
        print("error: worst-path cost $%.4f exceeds budget $%.2f, refusing to start."
              % (worst, a.budget), file=sys.stderr)
        raise SystemExit(3)
    log("worst-path cost $%.4f <= budget $%.2f, OK" % (worst, a.budget))

    key = api_key()
    spent = 0.0
    t_start = time.time()
    # v0.4: runtime budget circuit breaker (thread-safe, charge after each API call)
    runtime_budget = RuntimeBudget(a.budget, a.budget_headroom)

    # ---- v0.3a: dynamic member selection ----
    member_state = load_member_state(a.member_state)
    cap_scores = load_capability_scores(a.capability_scores)
    if a.member_state or a.capability_scores:
        models, dropped = select_members(models, member_state, cap_scores)
        if not models:
            log("fail-closed: dynamic member selection dropped all models")
            raise SystemExit(2)

    # ---- pre-panel health check ----
    if not a.no_health_check:
        models, hc_spent = health_check(models, key)
        spent += hc_spent
        if not models:
            log("fail-closed: all models failed health check, refusing empty run")
            raise SystemExit(2)
        log("health-check passed %d models" % len(models))

    # ---- v0.3b: load real-time context data ----
    ctx_data = load_context_data(a.context_data)
    if ctx_data:
        log("real-time data injected: %d facts" % len(ctx_data.get("facts", {})))
    panel_question = build_panel_prompt(a.question, ctx_data)
    panel_system = PANEL_SYSTEM if ctx_data else None

    # ---- v0.4: fetch PR diff for code review ----
    if a.pr_diff:
        diff = fetch_pr_diff(a.pr_diff)
        if diff:
            panel_question = (
                "=== PR DIFF (fetched from %s) ===\n%s\n"
                "=== END PR DIFF ===\n\n%s"
                % (a.pr_diff, diff, panel_question))

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
            log("[%d/%d] %s timeout (%.0fs), marked failed" % (i + 1, len(models), m,
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
            # v0.4: runtime budget circuit breaker
            try:
                runtime_budget.charge(r["cost"])
            except BudgetExceeded as be:
                log("BUDGET EXCEEDED: %s -- aborting" % be)
                raise SystemExit(3)
            if r["error"] or not r["text"]:
                reason = r["error"] or "empty response"
                log("[%d/%d] %s FAIL: %s" % (done, len(models), model, reason))
                answers.append({"model": model, "text": "",
                                "ok": False, "error": reason,
                                "truncated": False})
            else:
                ntok = (r["usage"] or {}).get("total_tokens", "?")
                trunc = " [truncated]" if r["truncated"] else ""
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
    log("estimated %.0fs more for judge + synth" % phase1_elapsed)

    # ---- phase 2: judge (v0.3a: dual-judge cross-validation) ----
    t1 = time.time()
    judges = [a.judge_model] + ([a.judge_model2] if a.judge_model2 else [])
    log("phase 2/3 judge: %s" % " + ".join(judges))
    # v0.4: anonymize answers for judges — model names hidden to mitigate
    # self-preference bias when a judge is also a panel member.
    ans_block = "\n\n".join(
        "【Answer %d】%s\n%s" % (i,
                                " (truncated)" if x["truncated"] else "",
                                x["text"])
        for i, x in enumerate(ok_answers))
    # v0.4: warn when a judge overlaps with panel membership
    # (only reachable with --allow-judge-overlap)
    for jm in judges:
        if jm in models:
            log("WARNING: judge %s is also a panel member "
                "(explicit --allow-judge-overlap; answers are anonymized)"
                % jm)

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
            log("judge %s timeout (%.0fs), degraded skip" % (jm, judge_timeout))
            fut.cancel()
        for fut in futs:
            jm = futs[fut]
            if fut in pending:
                judge_results[jm] = ({"cost": 0, "error": "timeout"}, None)
                continue
            try:
                jm2, jr, j = fut.result(timeout=0)
            except Exception as exc:
                log("judge %s error: %s" % (jm, exc))
                judge_results[jm] = ({"cost": 0, "error": str(exc)}, None)
                continue
            spent += jr["cost"]
            # v0.4: runtime budget circuit breaker
            if runtime_budget:
                try:
                    runtime_budget.charge(jr["cost"])
                except BudgetExceeded as be:
                    log("BUDGET EXCEEDED: %s -- aborting" % be)
                    raise SystemExit(3)
            judge_results[jm] = (jr, j)
            if j is None:
                log("judge %s invalid output (%s)" % (jm, jr["error"] or "contract violation"))
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
            log("dual judges agree, passed")
        else:
            log("dual judges disagree (%s) -> escalate to human" % dual_reason)
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
            out.append("===== Answer %d · %s =====" % (i, x["model"]))
            out.append(x["text"])
        if judge is not None:
            out.append("===== judge recommendation =====")
            dec_str = "; ".join(
                "#%d %s/%s" % (d["id"], d["verdict"], d["severity"])
                for d in judge["decisions"])
            out.append("winner: %s（%s）\ndecisions: %s"
                       % (judge.get("winner"),
                          judge.get("rationale") or "", dec_str))
            out.append("Human review: please reply with the chosen number.")
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
            log("judge has no clear winner, falling back to side-by-side display")
            for i, x in enumerate(usable):
                print("===== Answer %d · %s =====\n%s\n"
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
        log("synth failed (%s) -> degraded side-by-side display" % (sr["error"] or "empty"))
        for i, x in enumerate(usable):
            print("===== Answer %d · %s =====\n%s\n"
                  % (i, x["model"], x["text"]))
    else:
        print(sr["text"])
    # v0.3a: persist member stats
    if a.member_state:
        save_member_state(a.member_state, member_state)
        log("member state saved (%d models)" % len(member_state))
    log("done in %.1fs, spent $%.4f" % (time.time() - t_start, spent))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

