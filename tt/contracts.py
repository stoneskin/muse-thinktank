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
        return False, "judge output is not a JSON object"
    w = j.get("winner")
    if not (w is None or (isinstance(w, int) and not isinstance(w, bool)
                           and 0 <= w < n)):
        return False, "invalid winner (must be index 0-%d or null)" % (n - 1)
    ds = j.get("decisions")
    if not isinstance(ds, list) or len(ds) != n:
        return False, "decisions must cover all %d answers" % n
    seen = set()
    for d in ds:
        if not isinstance(d, dict):
            return False, "decision is not an object"
        i = d.get("id")
        if not isinstance(i, int) or isinstance(i, bool) \
                or not (0 <= i < n) or i in seen:
            return False, "invalid decision id"
        seen.add(i)
        if d.get("verdict") not in VERDICTS:
            return False, "invalid verdict (must be accept|reject|escalate)"
        if d.get("severity") not in SEVERITIES:
            return False, "invalid severity"
        if not isinstance(d.get("evidence"), str) or not d["evidence"].strip():
            return False, "evidence must not be empty"
    if j.get("confidence") not in ("high", "medium", "low"):
        return False, "invalid confidence"
    rej = {d["id"] for d in ds if d["verdict"] == "reject"}
    if isinstance(w, int) and w in rej:
        return False, "winner cannot be a rejected answer"
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

