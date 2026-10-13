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
    judges_agree, disagreement_entropy, repair_drifted,
    JUDGE_SYSTEM, JUDGE_TEMPLATE, REPAIR_TEMPLATE, SYNTH_SYSTEM, SYNTH_TEMPLATE,
    CRITIC_SYSTEM, CRITIC_TEMPLATE, validate_critic,
    REDTEAM_JUDGE_SYSTEM, REDTEAM_JUDGE_TEMPLATE, validate_redteam_judge,
)
from tt.budget import BudgetExceeded, RuntimeBudget, load_prices, worst_case_cost
from tt.context import (
    PANEL_SYSTEM, load_context_data, sanitize_context, build_panel_prompt,
)
from tt.members import (
    load_member_state, save_member_state, record_member, record_judge,
    availability, load_capability_scores, select_members,
)


def run_redteam(a, draft, key, member_state, t_start, spent, question):
    """v0.5 red-team: phase 4 (critics attack draft) + phase 5 (adjudicate).

    Returns exit code. Prints the attack report; never silently passes.
    """
    t3 = time.time()
    critic_models = ([m.strip() for m in a.critic_models.split(",") if m.strip()]
                     if a.critic_models
                     else [m.strip() for m in a.models.split(",") if m.strip()])
    log("phase 4/5 red-team: %d critics attack draft (%d chars)"
        % (len(critic_models), len(draft)))

    # Phase 4: critics attack in parallel
    critic_outputs = []
    with cf.ThreadPoolExecutor(max_workers=len(critic_models)) as ex:
        futs = {}
        for cm in critic_models:
            prompt = CRITIC_TEMPLATE.format(draft=draft[:6000],
                                            question=question[:500])
            futs[ex.submit(chat, cm,
                           [{"role": "system", "content": CRITIC_SYSTEM},
                            {"role": "user", "content": prompt}],
                           a.max_tokens, 0.7, a.panel_timeout, key)] = cm
        for fut in cf.as_completed(futs):
            cm = futs[fut]
            try:
                r = fut.result()
            except Exception as e:
                log("critic %s exception: %s" % (cm, e))
                continue
            spent += r["cost"]
            if r["error"] or not r["text"]:
                log("critic %s failed (%s)" % (cm, r["error"] or "empty"))
                continue
            c = extract_json(r["text"])
            ok, reason = validate_critic(c) if c else (False, "no JSON")
            if not ok:
                log("critic %s invalid output (%s)" % (cm, reason))
                continue
            critic_outputs.append({"model": cm, "findings": c["findings"]})
            log("critic %s: %d findings" % (cm, len(c["findings"])))
    if spent > a.budget:
        log("budget $%.2f exceeded after critics -- aborting" % a.budget)
        raise SystemExit(3)
    if not critic_outputs:
        log("fail-closed: no usable critic output -- refusing empty report")
        raise SystemExit(2)
    log("phase 4 done in %.1fs -- %d/%d critics ok (spent $%.4f)"
        % (time.time() - t3, len(critic_outputs), len(critic_models), spent))

    # Phase 5: adjudicator grades and filters
    t4 = time.time()
    log("phase 5/5 adjudicate: %s" % a.judge_model)
    critics_block = "\n\n".join(
        "--- critic: %s ---\n%s" % (c["model"], json.dumps(c["findings"],
                                     ensure_ascii=False, indent=2))
        for c in critic_outputs)
    ar = chat(a.judge_model,
              [{"role": "system", "content": REDTEAM_JUDGE_SYSTEM},
               {"role": "user",
                "content": REDTEAM_JUDGE_TEMPLATE.format(
                    n=len(critic_outputs), critics=critics_block,
                    draft=draft[:6000])}],
              max(1200, a.max_tokens), 0.3, a.panel_timeout, key)
    spent += ar["cost"]
    if spent > a.budget:
        log("budget $%.2f exceeded after adjudicator -- aborting" % a.budget)
        raise SystemExit(3)
    aj = extract_json(ar["text"]) if (not ar["error"] and ar["text"]) else None
    ok, reason = validate_redteam_judge(aj) if aj else (False, "no JSON")
    if not ok:
        log("adjudicator invalid (%s) -> raw critic dump" % reason)
        out = ["===== RED TEAM: RAW CRITIC OUTPUT (adjudicator failed) =====",
               ""]
        for c in critic_outputs:
            out.append("--- %s ---" % c["model"])
            for f in c["findings"]:
                out.append("[%s/%s] %s: %s"
                           % (f["severity"], f["category"], f["line"][:80],
                              f["attack"][:200]))
            out.append("")
        print("\n".join(out))
    else:
        kept = [f for f in aj["findings"] if f.get("keep")]
        dropped = [f for f in aj["findings"] if not f.get("keep")]
        out = ["===== RED TEAM REPORT =====",
               "verdict: %s (confidence: %s)" % (aj["verdict"],
                                                aj.get("confidence")),
               "",
               aj.get("summary") or "",
               "",
               "--- findings kept (%d) ---" % len(kept)]
        for f in kept:
            out.append("[%s/%s] \"%s\"" % (f["severity"], f["category"],
                                          f["line"][:100]))
            out.append("  -> %s" % f["attack"][:300])
        if dropped:
            out.append("")
            out.append("--- filtered out (%d nitpick/invalid) ---" % len(dropped))
            for f in dropped:
                out.append("[%s] \"%s\"" % (f["severity"], f["line"][:80]))
        out.append("")
        out.append("--- original draft (attacked) ---")
        out.append(draft[:3000])
        print("\n".join(out))
    log("phase 5 done in %.1fs (total %.1fs, spent $%.4f)"
        % (time.time() - t4, time.time() - t_start, spent))
    if a.member_state:
        save_member_state(a.member_state, member_state)
    return 0


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
    ap.add_argument("--priors", action="store_true",
                    help="v0.5: fetch public benchmark priors (LMArena + "
                         "OpenRouter, keyless, 6h cache) and use as "
                         "capability scores; own v1/v3 scores via "
                         "--capability-scores override these")
    ap.add_argument("--backup-models", default=None,
                    help="v0.5: comma-separated backup model ids; if panel "
                         "drops below --min-panel, backups are promoted "
                         "in order")
    ap.add_argument("--min-panel", type=int, default=2,
                    help="v0.5: minimum panel size; backups fill the gap, "
                         "fail-closed if still below")
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
    ap.add_argument("--red-team", action="store_true",
                    help="v0.5: red-team mode — standard panel+judge produces "
                         "a draft, then critics attack it and an adjudicator "
                         "grades findings by severity")
    ap.add_argument("--critic-models", default=None,
                    help="v0.5: comma-separated model ids for red-team critics "
                         "(default: same as --models panel)")
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
        if a.red_team:
            # v0.5: red-team adds critics + adjudicator, replaces synth
            n_critics = (len(a.critic_models.split(","))
                         if a.critic_models else len(models))
            n_calls = len(models) + n_judges + n_critics + 1
            worst_comp += n_critics * a.max_tokens + max(1200, a.max_tokens)
        print("Thinktank run estimate (worst path, v0.5):")
        print("  models: %s" % ", ".join(models))
        print("  judge: %s  synth: %s" % (judges_str, synth_model))
        if a.red_team:
            print("  red-team: ON (%d critics + adjudicator)" % n_critics)
        if a.backup_models:
            n_backup = len([m for m in a.backup_models.split(",") if m.strip()])
            print("  backups: %d (min panel %d)" % (n_backup, a.min_panel))
        print("  API calls: %d (panel %d + judge %d + synth 1%s)"
              % (n_calls, len(models), n_judges,
                 " + critics %d + adjudicator 1" % n_critics
                 if a.red_team else ""))
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
    if a.priors:
        # v0.5: public benchmark priors as base; own scores override
        from tt.priors import (build_priors, match_priors_to_models,
                               build_stability_priors)
        try:
            priors = match_priors_to_models(build_priors(), models)
            stab = build_stability_priors()
            for m in models:
                arena_s = priors.get(m, 0.5)
                stab_s = stab.get(m, 0.5)
                # blend: 70% capability, 30% stability
                blended = 0.7 * arena_s + 0.3 * stab_s
                cap_scores.setdefault(m, blended)
            log("priors: public benchmark + stability scores loaded for "
                "%d models (own --capability-scores take precedence)"
                % len(models))
        except Exception as e:
            log("priors fetch failed (%s), continuing without" % e)
    if a.member_state or a.capability_scores or a.priors:
        models, dropped = select_members(models, member_state, cap_scores)
        if not models:
            log("fail-closed: dynamic member selection dropped all models")
            raise SystemExit(2)

    # ---- pre-panel health check ----
    backups = ([m.strip() for m in a.backup_models.split(",") if m.strip()]
               if a.backup_models else [])
    if not a.no_health_check:
        models, hc_spent = health_check(models, key)
        spent += hc_spent
        # v0.5: promote backups if below min panel size
        # (keep trying backups until min reached or list exhausted)
        while len(models) < a.min_panel and backups:
            need = a.min_panel - len(models)
            promoted, hc2 = health_check(backups[:need], key)
            spent += hc2
            n_tried = min(need, len(backups))
            tried = backups[:n_tried]
            backups = backups[n_tried:]
            # drop the ones that failed health check, keep trying rest
            failed = [m for m in tried if m not in promoted]
            if failed:
                log("backups failed health check: %s" % ", ".join(failed))
            models.extend(promoted)
            if promoted:
                log("backups promoted: %s" % ", ".join(promoted))
            if not promoted and not backups:
                break
        if not models:
            log("fail-closed: all models failed health check, refusing empty run")
            raise SystemExit(2)
        if len(models) < a.min_panel:
            log("fail-closed: panel %d < min %d, no backups left"
                % (len(models), a.min_panel))
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
    # v0.5: if panel fell below min, try remaining backups
    if len(ok_answers) < a.min_panel and backups:
        need = a.min_panel - len(ok_answers)
        log("panel %d < min %d, trying %d backups"
            % (len(ok_answers), a.min_panel, min(need, len(backups))))
        b_models, bhc = health_check(backups[:need], key)
        spent += bhc
        backups = backups[need:]
        if b_models:
            # run backups through phase 1
            with cf.ThreadPoolExecutor(max_workers=len(b_models)) as ex2:
                bfuts = {}
                for bm in b_models:
                    prompt = build_panel_prompt(a.question, ctx_data)
                    if a.pr_diff and diff:
                        prompt = ("=== PR DIFF ===\n%s\n=== END ===\n\n%s"
                                  % (diff, prompt))
                    bfuts[ex2.submit(chat, bm,
                                     ([{"role": "system", "content": panel_system}]
                                      if panel_system else []) +
                                     [{"role": "user", "content": prompt}],
                                     a.max_tokens, a.temperature,
                                     a.panel_timeout, key)] = bm
                for fut in cf.as_completed(bfuts):
                    bm = bfuts[fut]
                    try:
                        r = fut.result()
                    except Exception as e:
                        log("backup %s exception: %s" % (bm, e))
                        continue
                    spent += r["cost"]
                    if r["error"] or not r["text"]:
                        log("backup %s failed (%s)"
                            % (bm, r["error"] or "empty"))
                        continue
                    ok_answers.append({"model": bm, "text": r["text"],
                                       "ok": True, "error": None,
                                       "truncated": r["truncated"]})
                    log("backup %s promoted to panel" % bm)
    if not ok_answers:
        log("fail-closed: no usable answer from panel -- refusing to synthesize")
        raise SystemExit(2)
    if len(ok_answers) < a.min_panel:
        log("fail-closed: panel %d < min %d after backups"
            % (len(ok_answers), a.min_panel))
        raise SystemExit(2)
    log("estimated %.0fs more for judge + synth" % phase1_elapsed)

    # ---- phase 2: judge (v0.3a: dual-judge cross-validation) ----
    t1 = time.time()
    judges = [a.judge_model] + ([a.judge_model2] if a.judge_model2 else [])
    log("phase 2/3 judge: %s" % " + ".join(judges))
    # v0.4: anonymize answers for judges — model names hidden to mitigate
    # self-preference bias when a judge is also a panel member.
    # v0.6.1: cap answer length for judge — very long answers (>9k tokens)
    # make judges lose the "JSON only" instruction (seen 2026-10-13:
    # both judges produced zero JSON on 19k-token input). 4000 chars
    # is enough to judge quality.
    JUDGE_ANSWER_CAP = 4000
    ans_block = "\n\n".join(
        "【Answer %d】%s\n%s" % (i,
                                " (truncated)" if x["truncated"] else "",
                                x["text"][:JUDGE_ANSWER_CAP] +
                                ("…[judge-truncated]" if len(x["text"]) > JUDGE_ANSWER_CAP else ""))
        for i, x in enumerate(ok_answers))
    # v0.4: warn when a judge overlaps with panel membership
    # (only reachable with --allow-judge-overlap)
    for jm in judges:
        if jm in models:
            log("WARNING: judge %s is also a panel member "
                "(explicit --allow-judge-overlap; answers are anonymized)"
                % jm)

    def run_judge(jm):
        msgs = [{"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user",
                 "content": JUDGE_TEMPLATE.format(n=len(ok_answers),
                                                  answers=ans_block)}]
        jr = chat(jm, msgs,
                  max(900, a.max_tokens), 0.3, a.panel_timeout, key)
        raw = extract_json(jr["text"]) if not jr["error"] else None
        j = normalize_judge(raw, len(ok_answers)) \
            if raw is not None else None
        # v0.6: repair-retry once on contract violation. Feed the specific
        # schema errors back; the model fixes its own format. Still
        # fail-closed: one retry max, then escalate as before.
        if j is None and not jr["error"] and raw is not None:
            _, errs = validate_judge(raw, len(ok_answers), collect_all=True)
            log("judge %s contract violation, repair-retry once (%d errors)"
                % (jm, len(errs)))
            repair_msgs = msgs + [
                {"role": "assistant", "content": jr["text"][:2000]},
                {"role": "user", "content": REPAIR_TEMPLATE.format(
                    errors="\n".join("- " + e for e in errs[:8]))},
            ]
            jr2 = chat(jm, repair_msgs,
                       max(900, a.max_tokens), 0.3, a.panel_timeout, key)
            retry_cost = jr["cost"] + jr2["cost"]
            # v0.4: runtime budget circuit breaker (retry cost counts)
            if runtime_budget:
                try:
                    runtime_budget.charge(jr2["cost"])
                except BudgetExceeded as be:
                    log("BUDGET EXCEEDED: %s -- aborting" % be)
                    raise SystemExit(3)
            raw2 = extract_json(jr2["text"]) if not jr2["error"] else None
            j2 = normalize_judge(raw2, len(ok_answers)) \
                if raw2 is not None else None
            if j2 is not None:
                # v0.6.1: 语义漂移检测 — repair 只许改格式，不许改判断
                if repair_drifted(raw, j2):
                    log("judge %s repair changed semantics (winner/verdict drift), "
                        "discarding repair, escalating" % jm)
                    jr["cost"] = retry_cost
                else:
                    log("judge %s repair-retry succeeded" % jm)
                    jr2["cost"] = retry_cost
                    jr = jr2
                    j = j2
            else:
                jr["cost"] = retry_cost
                log("judge %s repair-retry failed, escalating" % jm)
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
                # v0.6.1: 保存失败的原始输出用于诊断（/tmp 下，7 天清理）
                try:
                    import time as _t
                    _p = "/tmp/thinktank-judge-fail-%s-%d.txt" % (
                        jm.replace("/", "_").replace(":", "_"), int(_t.time()))
                    open(_p, "w").write(jr.get("text", "")[:4000])
                    log("judge %s raw output saved to %s" % (jm, _p))
                except Exception:
                    pass
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

    # ---- v0.5 red-team: phase 4 (critics) + phase 5 (adjudication) ----
    if a.red_team:
        # Draft = winner's text, or first usable answer if no clear winner
        w = judge.get("winner")
        if isinstance(w, int) and 0 <= w < len(ok_answers) and w not in rej:
            draft = ok_answers[w]["text"]
            log("red-team draft: winner #%d (%s)" % (w, ok_answers[w]["model"]))
        else:
            draft = usable[0]["text"]
            log("red-team draft: no clear winner, using first usable answer")
        if spent > a.budget:
            log("budget $%.2f exceeded before red-team -- aborting" % a.budget)
            raise SystemExit(3)
        return run_redteam(a, draft, key, member_state, t_start, spent,
                           a.question)

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

