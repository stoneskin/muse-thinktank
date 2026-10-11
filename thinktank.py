#!/usr/bin/env python3
"""muse-thinktank v0.3b -- multi-model deliberation orchestrator.

panel -> dual-judge -> synth/verdict, over OpenRouter /chat/completions.
Python standard library only. Reads OPENROUTER_API_KEY from the environment.

v0.3a (P0 reliability):
- Dual-judge cross-validation: two heterogeneous judges score independently;
  auto-pass only on agreement, else escalate to human.
- Dynamic member selection: schedule_score = capability × availability
  (sliding-window success rate × latency factor); < 0.6 filtered out.
- Debate convergence: disagreement entropy tracked per round; stops when
  entropy plateaus for 2 rounds (scaffolded for multi-round, currently 1).

v0.3b (freshness):
- Real-time data injection (--context-data): Muse pre-searches key facts
  and injects them into panel prompts with a [实时数据] marker. Panel
  models use injected numbers instead of stale training memory.
- Panel system prompt declares knowledge cutoff and bans fabricating numbers.

Usage:
    OPENROUTER_API_KEY=... thinktank.py ask \
        --models m1,m2,m3 --judge-model mj [--judge-model2 mj2] \
        [--show-all] [--verdict] [--synth-model ms] \
        [--budget 2.0] [--panel-timeout 120] [--max-tokens 800] \
        [--temperature 0.7] [--free-only --free-state PATH] \
        [--member-state PATH] [--capability-scores PATH] \
        [--estimate] [--prices PATH] [--no-health-check] \
        "question"

Modes:
    default    dual-judge -> synth  (final answer on stdout)
    --verdict  judges pick winner, winner's answer printed as-is (saves 1 call)
    --show-all print every answer + judge recommendation; the human judges.
    --estimate print the run plan (calls, worst-case tokens/cost/time) and exit
               without calling any API. Used for zero-round trigger confirm:
               show the estimate, user replies go / revise.

Judge contract (v0.2): the judge must return a strict JSON schema with a
per-answer decision (verdict: accept|reject|escalate, severity:
critical|major|minor|nitpick, evidence). The code validates the schema;
a non-compliant judge output counts as judge failure and falls back to
human verdict. verdict=escalate forces human verdict. severity=nitpick
decisions are filtered out before synth.

Dual-judge contract (v0.3a): with --judge-model2, both judges run in parallel
on the same answers. Auto-pass requires: same winner (or both null) AND
no escalate from either AND no critical disagreement on any single answer
(one accept + one reject on the same id = escalate). Otherwise the run
drops to --show-all mode for human verdict. Judge bias is tracked:
per-judge accept/reject rates are logged to --member-state for drift detection.

Dynamic member selection (v0.3a): --member-state keeps a sliding window
(last 20) of {ok, latency} per model. availability = success_rate *
(1 / (1 + mean_latency/10)). schedule_score = capability × availability
(capability from --capability-scores JSON, default 1.0). Models with
schedule_score < 0.6 are filtered before the panel. State is updated
after every run.

Cost fail-closed (v0.2): before phase 1 the worst-path cost is computed
(max tokens x prices). Unknown price for a paid model, or worst cost over
--budget, aborts the run before any call. --prices takes a JSON file or
string: {"model-id": {"input": 0.27, "output": 1.10}} ($ per 1M tokens).
Free-only runs are $0 by construction.

Health check (v0.2): each panel model gets a lightweight ping before the
panel; dead models are dropped for this run (logged). All dead -> abort
fail-closed. Disable with --no-health-check.

Exit codes: 0 ok, 2 no usable answer (fail-closed), 3 budget exceeded.
Progress goes to stderr; the final result goes to stdout.
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

API = "https://openrouter.ai/api/v1/chat/completions"
CATALOG = "https://openrouter.ai/api/v1/models"


def log(msg):
    print("[thinktank] " + msg, file=sys.stderr, flush=True)


def api_key():
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        print("error: OPENROUTER_API_KEY is not set", file=sys.stderr)
        raise SystemExit(2)
    return key


def chat(model, messages, max_tokens, temperature, timeout, key):
    """One chat completion. Returns dict(text, usage, cost, error, elapsed,
    truncated, finish_reason)."""
    payload = {"model": model, "messages": messages,
               "max_tokens": max_tokens, "temperature": temperature}
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": "muse-thinktank/0.1",
                 "Authorization": "Bearer " + key})
    t0 = time.time()

    def fail(reason):
        return {"text": "", "usage": {}, "cost": 0.0, "error": reason,
                "elapsed": time.time() - t0, "truncated": False,
                "finish_reason": ""}

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            body = ""
        return fail("HTTP %d: %s" % (exc.code, body))
    except Exception as exc:
        return fail("network: %s" % exc)
    err = data.get("error")
    if err:
        return fail("API: %s" % json.dumps(err)[:300])
    choices = data.get("choices") or []
    text = ""
    finish_reason = ""
    if choices:
        text = (choices[0].get("message", {}).get("content") or "").strip()
        finish_reason = choices[0].get("finish_reason") or ""
    usage = data.get("usage") or {}
    try:
        cost = float(usage.get("cost") or 0)
    except (ValueError, TypeError):
        cost = 0.0
    return {"text": text, "usage": usage, "cost": cost, "error": None,
            "elapsed": time.time() - t0,
            "truncated": finish_reason == "length",
            "finish_reason": finish_reason}


def free_ids(state_path):
    """Exact verified-free ids from a models.py scan report (fresh or cached)."""
    report = None
    if state_path and os.path.exists(state_path):
        try:
            report = json.load(open(state_path))
            age = (dt.datetime.now(dt.timezone.utc)
                   - dt.datetime.fromisoformat(report["checked_at"]))
            if age > dt.timedelta(hours=24) or "free" not in report:
                report = None
        except (ValueError, KeyError, OSError):
            report = None
    if report is None:
        req = urllib.request.Request(CATALOG,
                                     headers={"User-Agent": "muse-thinktank/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            entries = json.load(resp).get("data", [])

        def z(v):
            try:
                return float(v) == 0
            except (ValueError, TypeError):
                return False

        free = []
        for m in entries:
            pr = m.get("pricing") or {}
            if z(pr.get("prompt")) and z(pr.get("completion")):
                free.append(m["id"])
        return set(free)
    return set(m["id"] for m in report["free"])


def resolve_free(model_id, known):
    """Fail-closed: exact verified-free id, or :free auto-correct with warning,
    else refuse. A missing :free suffix silently routes to the PAID variant."""
    model_id = (model_id or "").strip()
    if model_id in known:
        return model_id
    suffixed = model_id if model_id.endswith(":free") else model_id + ":free"
    if suffixed in known:
        log("WARNING: '%s' is not verified-free; using '%s'. "
            "Calling '%s' directly would use the PAID variant."
            % (model_id, suffixed, model_id))
        return suffixed
    raise SystemExit("error: '%s' is not a verified-free model id. "
                     "Refusing: calling it could incur charges." % model_id)


JUDGE_SYSTEM = "你是中立裁判。只输出 JSON，不要输出其他文字。"

JUDGE_TEMPLATE = """以下 {n} 个 AI 模型回答了同一个问题。请裁判并只输出 JSON，严格遵守 schema：

{{"winner": 0,
 "decisions": [{{"id": 0, "verdict": "accept", "severity": "major", "evidence": "一句话证据"}}],
 "consensus": "各家都同意的结论",
 "disagreements": [{{"topic": "", "positions": [{{"answer": 0, "stance": ""}}]}}],
 "unique_insights": [{{"answer": 1, "insight": "只有这家提到的真东西"}}],
 "confidence": "high",
 "rationale": "为什么选它",
 "needs_human": false}}

规则：
- decisions 必须覆盖全部 {n} 个回答（id 从 0 起）；verdict 只能是 accept|reject|escalate；severity 只能是 critical|major|minor|nitpick；evidence 不许为空。
- 空答、答非所问、明显幻觉 → verdict=reject，severity=critical，evidence 写明理由；winner 不能是被 reject 的。
- 拿不准、需要人拍板的 → verdict=escalate，needs_human=true。
- 无明显赢家时 winner=null。
- critique 按 severity 标注；nitpick 不计入胜负、不进入终审。

{answers}"""

SYNTH_SYSTEM = "你是综合者。直接输出最终答案，不要解释过程。"

SYNTH_TEMPLATE = """根据裁判报告和各家原答案，写出最终答案。
规则：遇到矛盾先停——存疑的前提必须先解决/丢弃/对冲，不许在上面堆结论；
fragile_claims 必须对冲表述、不许当事实写；
severity=nitpick 的 critique 已被过滤，不用管。

裁判报告：
{judge}

原答案：
{answers}"""


def extract_json(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except ValueError:
            return None
    return None


VERDICTS = ("accept", "reject", "escalate")
SEVERITIES = ("critical", "major", "minor", "nitpick")


def validate_judge(j, n):
    """Strict judge-contract check. Returns (ok, reason)."""
    if not isinstance(j, dict):
        return False, "judge 输出不是 JSON object"
    w = j.get("winner")
    if not (w is None or (isinstance(w, int) and not isinstance(w, bool)
                           and 0 <= w < n)):
        return False, "winner 非法（必须是 0-%d 的下标或 null）" % (n - 1)
    ds = j.get("decisions")
    if not isinstance(ds, list) or len(ds) != n:
        return False, "decisions 必须覆盖全部 %d 个回答" % n
    seen = set()
    for d in ds:
        if not isinstance(d, dict):
            return False, "decision 不是 object"
        i = d.get("id")
        if not isinstance(i, int) or isinstance(i, bool) \
                or not (0 <= i < n) or i in seen:
            return False, "decision id 非法"
        seen.add(i)
        if d.get("verdict") not in VERDICTS:
            return False, "verdict 非法（只许 accept|reject|escalate）"
        if d.get("severity") not in SEVERITIES:
            return False, "severity 非法"
        if not isinstance(d.get("evidence"), str) or not d["evidence"].strip():
            return False, "evidence 不许为空"
    if j.get("confidence") not in ("high", "medium", "low"):
        return False, "confidence 非法"
    rej = {d["id"] for d in ds if d["verdict"] == "reject"}
    if isinstance(w, int) and w in rej:
        return False, "winner 不能是被 reject 的"
    return True, ""


def normalize_judge(j, n):
    """Validate against the v0.2 contract; fall back to the legacy shape
    (winner/rejected/reasons/confidence) and normalize it. Returns the
    normalized dict, or None when the judge output is unusable."""
    if isinstance(j, dict):
        ok, _ = validate_judge(j, n)
        if ok:
            return j
        rej = j.get("rejected")
        if isinstance(rej, list):
            rej_ids = {i for i in rej
                       if isinstance(i, int) and not isinstance(i, bool)
                       and 0 <= i < n}
            j2 = dict(j)
            j2["decisions"] = [
                {"id": i,
                 "verdict": "reject" if i in rej_ids else "accept",
                 "severity": "critical" if i in rej_ids else "minor",
                 "evidence": "legacy judge format"}
                for i in range(n)]
            ok2, _ = validate_judge(j2, n)
            if ok2:
                log("judge 用了旧格式，已兼容转换")
                return j2
    return None


def judge_needs_human(j):
    if not isinstance(j, dict):
        return False
    if j.get("needs_human"):
        return True
    return any(d.get("verdict") == "escalate"
               for d in j.get("decisions", []) if isinstance(d, dict))


def load_prices(spec):
    """--prices: JSON string or path to JSON file:
    {"model-id": {"input": 0.27, "output": 1.10}} ($ per 1M tokens)."""
    if not spec:
        return {}
    text = spec
    if os.path.exists(spec):
        text = open(spec).read()
    try:
        data = json.loads(text)
    except ValueError:
        raise SystemExit("error: --prices 解析失败（不是合法 JSON）")
    if not isinstance(data, dict):
        raise SystemExit("error: --prices 必须是 {model: {input, output}}")
    return data


def worst_case_cost(models, judge_models, synth_model, question, max_tokens,
                   prices, free_set):
    """Worst-path cost in USD, or (None, missing_model) when a paid model
    has no price entry. Free-verified models cost $0 by construction."""
    unknown = []
    per1m = {}
    for m in set(models + judge_models + [synth_model]):
        base = m[:-5] if m.endswith(":free") else m
        if m.endswith(":free") or base in free_set or m in free_set:
            # :free 后缀 = 明确走免费端点；free_set 覆盖无后缀的免费 id
            per1m[m] = (0.0, 0.0)
        elif m in prices:
            p = prices[m]
            try:
                per1m[m] = (float(p["input"]), float(p["output"]))
            except (KeyError, ValueError, TypeError):
                unknown.append(m)
        else:
            unknown.append(m)
    if unknown:
        return None, unknown[0]
    # worst case: every call maxes out completions; prompts ~ chars/4
    judge_max = max(900, max_tokens)
    synth_max = max(1200, max_tokens)
    q_tok = len(question) / 4.0
    total = 0.0
    for m in models:
        pi, po = per1m[m]
        total += q_tok / 1e6 * pi + max_tokens / 1e6 * po
    # judge prompt carries all answers at worst-case length
    judge_prompt = (len(models) * max_tokens * 2 + len(question)) / 4.0
    for jm in judge_models:
        pj_i, pj_o = per1m[jm]
        total += judge_prompt / 1e6 * pj_i + judge_max / 1e6 * pj_o
    ps_i, ps_o = per1m[synth_model]
    total += judge_prompt / 1e6 * ps_i + synth_max / 1e6 * ps_o
    return total, None


def health_check(models, key, timeout=20):
    """Lightweight ping per model before the panel. Returns (alive, spent).
    A model that errors or returns empty is dropped for this run.
    Note: max_tokens must be generous (>=50) -- some free models return
    empty with finish_reason=length when the token budget is tiny."""
    alive, spent = [], 0.0
    for m in models:
        r = chat(m, [{"role": "user",
                      "content": "Reply with the single word: ok"}],
                 50, 0.0, timeout, key)
        spent += r["cost"]
        if not r["error"] and r["text"].strip():
            alive.append(m)
        else:
            log("health-check: %s 不可用（%s），本轮剔除"
                % (m, r["error"] or "空返回"))
    return alive, spent


# ---- v0.3b: real-time data injection ----

PANEL_SYSTEM = """你的训练数据有知识截止日期，之后的具体数字（股价、财报、增长率、PE 等）可能已过时。
规则：
1. 先用【实时数据】区块中的数字做分析，不要用你记忆中的旧数字。
2. 如果【实时数据】没有某个数字，标注 [数据缺失] 而不是编造。
3. 框架性判断（逻辑、风险类别、方法论）可以用你的知识，不受影响。"""


def load_context_data(path):
    """{"preamble": str, "facts": {key: value}} or None."""
    if path and os.path.exists(path):
        try:
            d = json.load(open(path))
            return d if isinstance(d, dict) else None
        except (ValueError, OSError):
            pass
    return None


def build_panel_prompt(question, ctx):
    """Append [实时数据] block if context data is provided."""
    if not ctx:
        return question
    facts = ctx.get("facts", {})
    lines = ["", "【实时数据】（调度器实时搜索注入，请优先使用以下数字，不要用训练记忆中的旧值）"]
    if ctx.get("preamble"):
        lines.append(ctx["preamble"])
    for k, v in facts.items():
        lines.append("- %s：%s" % (k, v))
    as_of = ctx.get("as_of", "")
    if as_of:
        lines.append("（数据时间：%s）" % as_of)
    return question + "\n" + "\n".join(lines)

MEMBER_WINDOW = 20  # sliding window size for availability tracking
MEMBER_MIN_SCORE = 0.6  # schedule_score below this -> filtered out


def load_member_state(path):
    """{model_id: {"ok": [bool...], "lat": [float...], "judge_accept": int,
    "judge_reject": int}} — sliding windows, newest last."""
    if path and os.path.exists(path):
        try:
            return json.load(open(path))
        except (ValueError, OSError):
            pass
    return {}


def save_member_state(path, state):
    if not path:
        return
    try:
        json.dump(state, open(path, "w"), ensure_ascii=False, indent=1)
    except OSError as exc:
        log("member-state 保存失败：%s" % exc)


def record_member(state, model, ok, latency):
    e = state.setdefault(model, {"ok": [], "lat": [],
                                 "judge_accept": 0, "judge_reject": 0})
    e["ok"].append(bool(ok))
    e["lat"].append(float(latency))
    e["ok"] = e["ok"][-MEMBER_WINDOW:]
    e["lat"] = e["lat"][-MEMBER_WINDOW:]


def record_judge(state, judge_model, n_accept, n_reject):
    e = state.setdefault(judge_model, {"ok": [], "lat": [],
                                       "judge_accept": 0, "judge_reject": 0})
    e["judge_accept"] += n_accept
    e["judge_reject"] += n_reject


def availability(model, state):
    """success_rate * (1 / (1 + mean_latency/120)). No history -> 1.0.
    Latency penalty is gentle: 60s -> 0.67x, 120s -> 0.5x. Reliability
    (success rate) dominates, not speed."""
    e = state.get(model)
    if not e or not e["ok"]:
        return 1.0
    sr = sum(e["ok"]) / len(e["ok"])
    ml = sum(e["lat"]) / len(e["lat"]) if e["lat"] else 0
    return sr * (1.0 / (1.0 + ml / 120.0))


def load_capability_scores(path):
    """{model_id: 0.0-1.0}. Missing file or missing model -> 1.0."""
    if path and os.path.exists(path):
        try:
            d = json.load(open(path))
            return d if isinstance(d, dict) else {}
        except (ValueError, OSError):
            pass
    return {}


def select_members(models, state, cap_scores):
    """Filter by schedule_score = capability × availability."""
    kept, dropped = [], []
    for m in models:
        cap = float(cap_scores.get(m, 1.0))
        avail = availability(m, state)
        score = cap * avail
        if score >= MEMBER_MIN_SCORE:
            kept.append(m)
            log("成员选择：%s 通过（能力 %.2f × 可用 %.2f = %.2f）"
                % (m, cap, avail, score))
        else:
            dropped.append(m)
            log("成员选择：%s 剔除（%.2f < %.2f）" % (m, score, MEMBER_MIN_SCORE))
    return kept, dropped


# ---- v0.3a: dual-judge cross-validation ----

def judges_agree(j1, j2, n):
    """Returns (agree, reason). Auto-pass requires same winner (or both
    null), no escalate from either, and no critical accept/reject split
    on any single answer."""
    if j1 is None or j2 is None:
        return False, "某 judge 输出无效"
    if j1.get("winner") != j2.get("winner"):
        return False, "winner 不一致（%s vs %s）" % (j1.get("winner"),
                                                    j2.get("winner"))
    d1 = {d["id"]: d for d in j1.get("decisions", [])}
    d2 = {d["id"]: d for d in j2.get("decisions", [])}
    for i in range(n):
        v1 = (d1.get(i) or {}).get("verdict")
        v2 = (d2.get(i) or {}).get("verdict")
        if "escalate" in (v1, v2):
            return False, "回答%d 有 escalate" % i
        if {v1, v2} == {"accept", "reject"}:
            return False, "回答%d judge 分歧（accept vs reject）" % i
    return True, ""


def disagreement_entropy(judge, n):
    """Weighted disagreement mass: sum over answers of severity weight
    where judges disagree or verdict != accept. Used for convergence
    tracking across debate rounds (v0.3a: single round scaffold)."""
    if not judge:
        return float("inf")
    w = {"critical": 4.0, "major": 2.0, "minor": 0.5, "nitpick": 0.1}
    total = 0.0
    for d in judge.get("decisions", []):
        if d.get("verdict") != "accept":
            total += w.get(d.get("severity"), 1.0)
    return total


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

    with cf.ThreadPoolExecutor(max_workers=len(models)) as ex:
        futs = {ex.submit(run_one, i, m): (i, m)
                for i, m in enumerate(models)}
        done = 0
        for fut in cf.as_completed(futs, timeout=a.panel_timeout + 30):
            i, m = futs[fut]
            try:
                idx, model, r = fut.result()
            except Exception as exc:
                r = {"text": "", "cost": 0.0,
                     "error": "worker: %s" % exc, "elapsed": 0}
            done += 1
            spent += r["cost"]
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
    with cf.ThreadPoolExecutor(max_workers=len(judges)) as ex:
        futs = {ex.submit(run_judge, jm): jm for jm in judges}
        for fut in cf.as_completed(futs, timeout=a.panel_timeout + 30):
            jm, jr, j = fut.result()
            spent += jr["cost"]
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
