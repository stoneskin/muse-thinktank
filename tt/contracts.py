"""v0.4 module: tt/contracts.py."""

import json
import re
from .util import log

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

