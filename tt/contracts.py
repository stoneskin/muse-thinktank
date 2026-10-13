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


def validate_judge(j, n, collect_all=False):
    """Strict judge-contract check. Returns (ok, reason) or (ok, [reasons])."""
    errs = []
    if not isinstance(j, dict):
        errs.append("judge output is not a JSON object")
    else:
        w = j.get("winner")
        if not (w is None or (isinstance(w, int) and not isinstance(w, bool)
                               and 0 <= w < n)):
            errs.append("invalid winner (must be index 0-%d or null)" % (n - 1))
        ds = j.get("decisions")
        if not isinstance(ds, list) or len(ds) != n:
            errs.append("decisions must cover all %d answers" % n)
        else:
            seen = set()
            for d in ds:
                if not isinstance(d, dict):
                    errs.append("decision is not an object")
                    continue
                i = d.get("id")
                if not isinstance(i, int) or isinstance(i, bool) \
                        or not (0 <= i < n) or i in seen:
                    errs.append("invalid decision id (must be unique int 0-%d)" % (n - 1))
                else:
                    seen.add(i)
                if d.get("verdict") not in VERDICTS:
                    errs.append("invalid verdict (must be accept|reject|escalate)")
                if d.get("severity") not in SEVERITIES:
                    errs.append("invalid severity (must be critical|major|minor|nitpick)")
                if not isinstance(d.get("evidence"), str) or not d["evidence"].strip():
                    errs.append("evidence must not be empty")
        if j.get("confidence") not in ("high", "medium", "low"):
            errs.append("invalid confidence (must be high|medium|low)")
        rej = set()
        if isinstance(j.get("decisions"), list):
            rej = {d["id"] for d in j["decisions"]
                   if isinstance(d, dict) and d.get("verdict") == "reject"
                   and isinstance(d.get("id"), int)}
        if isinstance(w, int) and w in rej:
            errs.append("winner cannot be a rejected answer")
    ok = len(errs) == 0
    if collect_all:
        return ok, errs
    return ok, (errs[0] if errs else "")


def _lenient_fix(j, n):
    """v0.6: cosmetic auto-repairs that don't change meaning.

    - enum case-insensitive (Accept -> accept)
    - numeric strings -> int ("1" -> 1)
    - missing confidence -> medium
    Never maps synonyms (approved -> accept) — that's semantic, leave it
    for the repair-retry path.
    Returns fixed copy, or None if input isn't a dict.
    """
    if not isinstance(j, dict):
        return None
    import copy
    f = copy.deepcopy(j)
    w = f.get("winner")
    if isinstance(w, str) and w.strip().lstrip("-").isdigit():
        f["winner"] = int(w.strip())
    c = f.get("confidence")
    if isinstance(c, str) and c.lower() in ("high", "medium", "low"):
        f["confidence"] = c.lower()
    elif c is None:
        f["confidence"] = "medium"
    ds = f.get("decisions")
    if isinstance(ds, list):
        for d in ds:
            if not isinstance(d, dict):
                continue
            i = d.get("id")
            if isinstance(i, str) and i.strip().lstrip("-").isdigit():
                d["id"] = int(i.strip())
            v = d.get("verdict")
            if isinstance(v, str) and v.lower() in VERDICTS:
                d["verdict"] = v.lower()
            s = d.get("severity")
            if isinstance(s, str) and s.lower() in SEVERITIES:
                d["severity"] = s.lower()
    return f


def normalize_judge(j, n):
    """Validate against the v0.2 contract; fall back to the legacy shape
    (winner/rejected/reasons/confidence) and normalize it. Returns the
    normalized dict, or None when the judge output is unusable."""
    if isinstance(j, dict):
        ok, _ = validate_judge(j, n)
        if ok:
            return j
        # v0.6: cosmetic leniency before giving up — fix case/number
        # formatting without changing meaning; log when applied.
        fixed = _lenient_fix(j, n)
        if fixed is not None:
            ok2, _ = validate_judge(fixed, n)
            if ok2:
                log("judge output auto-repaired (cosmetic: case/number format)")
                return fixed
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
                log("judge used legacy format, converted for compatibility")
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
        return False, "a judge output is invalid"
    if j1.get("winner") != j2.get("winner"):
        return False, "winner mismatch (%s vs %s)" % (j1.get("winner"),
                                                    j2.get("winner"))
    d1 = {d["id"]: d for d in j1.get("decisions", [])}
    d2 = {d["id"]: d for d in j2.get("decisions", [])}
    for i in range(n):
        v1 = (d1.get(i) or {}).get("verdict")
        v2 = (d2.get(i) or {}).get("verdict")
        if "escalate" in (v1, v2):
            return False, "answer %d has escalate" % i
        if {v1, v2} == {"accept", "reject"}:
            return False, "answer %d judge disagreement (accept vs reject)" % i
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


JUDGE_SYSTEM = "You are a neutral judge. Output JSON only, no other text."

REPAIR_TEMPLATE = """Your previous judge output failed schema validation with these errors:
{errors}

Resend ONLY the corrected JSON, no other text. Keep your judgments (winner, verdicts, evidence) exactly the same — fix only the format to match the schema."""


def _ci_get(d, key):
    """大小写不敏感取 dict 值（repair_drifted 需比对未归一化的 raw）。"""
    if not isinstance(d, dict):
        return None
    if key in d:
        return d[key]
    lk = key.lower()
    for k, v in d.items():
        if isinstance(k, str) and k.lower() == lk:
            return v
    return None


def _semantic_core(j):
    """提取判断的语义核心 (winner, {id: verdict})，用于检测 repair 语义漂移."""
    if not isinstance(j, dict):
        return None
    w = _ci_get(j, "winner")
    if isinstance(w, str) and w.strip().lstrip("-").isdigit():
        w = int(w.strip())
    if not (w is None or (isinstance(w, int) and not isinstance(w, bool))):
        w = "?"
    verdicts = {}
    ds = _ci_get(j, "decisions")
    if isinstance(ds, list):
        for d in ds:
            if not isinstance(d, dict):
                continue
            i = _ci_get(d, "id")
            if isinstance(i, str) and i.strip().lstrip("-").isdigit():
                i = int(i.strip())
            v = _ci_get(d, "verdict")
            if isinstance(v, str):
                v = v.lower().strip()
            if isinstance(i, int) and not isinstance(i, bool):
                verdicts[i] = v
    return (w, verdicts)


def repair_drifted(original_raw, repaired):
    """检查 repair 是否改变了语义（winner/verdicts）。True=漂移，不可信."""
    c1 = _semantic_core(original_raw)
    c2 = _semantic_core(repaired)
    if c1 is None or c2 is None:
        return True  # 无法比较，保守起见视为漂移
    w1, v1 = c1
    w2, v2 = c2
    # winner：原输出有明确 winner 且被改了 → 漂移
    if w1 not in (None, "?") and w2 not in (None, "?") and w1 != w2:
        return True
    # verdicts：原输出有的 verdict 被改了 → 漂移
    for i, v in v1.items():
        if i in v2 and v2[i] not in (None, "?") and v not in (None, "?") and v != v2[i]:
            return True
    return False

JUDGE_TEMPLATE = """{n} AI models answered the same question. Judge them and output JSON only, strictly following the schema:

{{"winner": 0,
 "decisions": [{{"id": 0, "verdict": "accept", "severity": "major", "evidence": "one-sentence evidence"}}],
 "consensus": "conclusion all answers agree on",
 "disagreements": [{{"topic": "", "positions": [{{"answer": 0, "stance": ""}}]}}],
 "unique_insights": [{{"answer": 1, "insight": "genuine point only this answer made"}}],
 "confidence": "high",
 "rationale": "why this winner",
 "needs_human": false}}

Rules:
- decisions must cover all {n} answers (id from 0); verdict must be accept|reject|escalate; severity must be critical|major|minor|nitpick; evidence must not be empty.
- Empty answer, off-topic, or obvious hallucination → verdict=reject, severity=critical, explain in evidence; winner cannot be a rejected answer.
- Uncertain, needs human call → verdict=escalate, needs_human=true.
- winner=null when no clear winner.
- Label critiques by severity; nitpicks don't count toward win/loss and don't go to human review.

{answers}"""

SYNTH_SYSTEM = "You are a synthesizer. Output the final answer directly, do not explain the process."


SYNTH_TEMPLATE = """Write the final answer based on the judge report and the original answers.
Rules: when answers contradict, stop first — a doubtful premise must be resolved, discarded, or hedged before building conclusions on it;
fragile_claims must be hedged, never stated as fact;
critiques with severity=nitpick were already filtered, ignore them.

Judge report:
{judge}

Original answers:
{answers}"""


# ---- v0.5 red-team contracts ----

CRITIC_SYSTEM = "You are a red-team attacker. Output JSON only, no other text."

CRITIC_TEMPLATE = """You are attacking a draft answer. Find its weaknesses — do NOT praise it.
Output JSON only, strictly following the schema:

{{"findings": [{{"severity": "critical", "category": "factual|logical|tone|missing", "line": "exact quoted line or phrase", "attack": "one-sentence specific criticism"}}]}}

Severity guide:
- critical: would undermine credibility if published (false claim, logical hole, disprovable statement)
- major: weakens the piece significantly (overpromise, hand-waving, unaddressed objection)
- minor: should be fixed but not embarrassing (awkward phrasing, weak transition)
- nitpick: trivial style preference — still list it, it will be filtered later

Attack angles:
1. Factual overclaims: statements that can't be verified or are likely false
2. Logical gaps: conclusions that don't follow from premises
3. Skeptic test: what would a hostile expert reader challenge?
4. Tone: hype, defensiveness, condescension, weasel words
5. Missing objections: strongest counter-argument the draft doesn't address

Draft to attack:
{draft}

Original question (for context):
{question}"""


def validate_critic(c):
    """Validate red-team critic output. Returns (ok, reason)."""
    if not isinstance(c, dict):
        return False, "critic output is not a JSON object"
    fs = c.get("findings")
    if not isinstance(fs, list):
        return False, "findings must be a list"
    for f in fs:
        if not isinstance(f, dict):
            return False, "finding is not an object"
        if f.get("severity") not in SEVERITIES:
            return False, "invalid severity in finding"
        if f.get("category") not in ("factual", "logical", "tone", "missing"):
            return False, "invalid category in finding"
        if not isinstance(f.get("line"), str) or not f["line"].strip():
            return False, "line must not be empty"
        if not isinstance(f.get("attack"), str) or not f["attack"].strip():
            return False, "attack must not be empty"
    return True, ""


REDTEAM_JUDGE_SYSTEM = "You are a red-team adjudicator. Output JSON only, no other text."

REDTEAM_JUDGE_TEMPLATE = """{n} critics attacked the same draft. Adjudicate their findings and output JSON only:

{{"verdict": "revise|accept",
 "findings": [{{"severity": "critical", "category": "", "line": "", "attack": "", "keep": true}}],
 "summary": "one-paragraph assessment of whether the draft survives",
 "confidence": "high"}}

Rules:
- Merge duplicate findings (same line, same point) — keep the sharpest wording.
- Re-grade severity if a critic over- or under-rated. Be strict: most "major" claims are "minor".
- keep=false for nitpicks and for attacks that are wrong (the critic misread the draft).
- verdict=revise if any critical or major findings survive with keep=true; otherwise accept.
- findings must be a list; each needs severity (critical|major|minor|nitpick), category, line, attack, keep (boolean).

Critic outputs:
{critics}

Original draft:
{draft}"""


def validate_redteam_judge(j):
    """Validate red-team adjudicator output. Returns (ok, reason)."""
    if not isinstance(j, dict):
        return False, "not a JSON object"
    if j.get("verdict") not in ("revise", "accept"):
        return False, "verdict must be revise|accept"
    fs = j.get("findings")
    if not isinstance(fs, list):
        return False, "findings must be a list"
    for f in fs:
        if not isinstance(f, dict):
            return False, "finding is not an object"
        if f.get("severity") not in SEVERITIES:
            return False, "invalid severity"
        if not isinstance(f.get("keep"), bool):
            return False, "keep must be boolean"
    if j.get("confidence") not in ("high", "medium", "low"):
        return False, "invalid confidence"
    return True, ""

