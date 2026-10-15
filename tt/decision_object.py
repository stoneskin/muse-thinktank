"""v0.14 module: tt/decision_object.py.

Machine-readable Decision Object derived from a completed Run Record.

Schema version: 1. Never remove fields; only add (with defaults).
Reuses run_record conventions: versioned schema, _redact for PII,
_sha256_of for integrity. No LLM calls — pure derivation from the
structured data already in the record (judge output, stages, facts).
"""

import json
import sys

from tt.run_record import _redact, _sha256_of

SCHEMA_VERSION = 1

# entropy scale: entropy=0 -> 1.0, entropy=4 -> 0.5, entropy=inf -> ~0
_ENTROPY_SCALE = 4.0
# confidence cap when human review is still needed
_HUMAN_CAP = 0.5


def _confidence_from_judge(judge_stage, panel_size):
    """Derive (confidence, factors) from judge stage data.

    Returns (float|None, dict). None when no usable judge output.
    """
    factors = {
        "judge_entropy": None,
        "panel_size": panel_size,
        "needs_human": False,
        "notes": "",
    }
    if not isinstance(judge_stage, dict):
        factors["notes"] = "no judge stage in record"
        return None, factors

    entropy = judge_stage.get("entropy")
    factors["judge_entropy"] = entropy
    if entropy is None or entropy == float("inf"):
        factors["notes"] = "judge entropy unavailable or infinite"
        return None, factors

    outputs = judge_stage.get("outputs") or []
    needs_human = False
    for o in outputs:
        res = (o or {}).get("result") or {}
        if not isinstance(res, dict):
            continue
        if res.get("needs_human"):
            needs_human = True
            break
        for d in res.get("decisions", []):
            if isinstance(d, dict) and d.get("verdict") == "escalate":
                needs_human = True
                break
    factors["needs_human"] = needs_human

    conf = 1.0 / (1.0 + entropy / _ENTROPY_SCALE)
    notes = "1/(1+entropy/%.1f); entropy=%.2f" % (_ENTROPY_SCALE, entropy)
    if needs_human:
        conf = min(conf, _HUMAN_CAP)
        notes += "; capped at %.1f (human review needed)" % _HUMAN_CAP
    factors["notes"] = notes
    return round(conf, 4), factors


def _disagreements_from_judge(judge_stage, panel_models):
    """Normalize judge disagreements, enriching with model names."""
    out = []
    if not isinstance(judge_stage, dict):
        return out
    for o in judge_stage.get("outputs") or []:
        res = (o or {}).get("result") or {}
        if not isinstance(res, dict):
            continue
        for dg in res.get("disagreements", []):
            if not isinstance(dg, dict):
                continue
            positions = []
            for p in dg.get("positions", []):
                if not isinstance(p, dict):
                    continue
                idx = p.get("answer")
                positions.append({
                    "answer": idx,
                    "model": panel_models[idx]
                    if isinstance(idx, int) and 0 <= idx < len(panel_models)
                    else None,
                    "stance": p.get("stance"),
                })
            out.append({
                "topic": dg.get("topic"),
                "positions": positions,
            })
        break  # first judge only; dual-judge merge is out of scope for v1
    return _redact(out)


def _evidence_from_record(record):
    """Collect evidence: context facts + judge evidence strings + consensus."""
    ev = []
    facts = record.get("context_facts")
    if isinstance(facts, dict):
        for k, v in facts.items():
            ev.append({"source": "context_facts",
                       "text": "%s: %s" % (k, v)})
    elif isinstance(facts, list):
        for item in facts:
            ev.append({"source": "context_facts",
                       "text": str(item)})
    stages = record.get("stages", {})
    judge_stage = stages.get("judge")
    if isinstance(judge_stage, dict):
        for o in judge_stage.get("outputs") or []:
            res = (o or {}).get("result") or {}
            if not isinstance(res, dict):
                continue
            if res.get("consensus"):
                ev.append({"source": "judge_consensus",
                           "text": res["consensus"]})
            for d in res.get("decisions", []):
                if isinstance(d, dict) and d.get("evidence"):
                    ev.append({"source": "judge",
                               "text": "answer #%s: %s"
                               % (d.get("id"), d["evidence"])})
            break
    return _redact(ev)


def _actions_from_judge(judge_stage):
    """Derive follow-up actions from structured judge output.

    No NLP extraction — only escalations and critical/major
    non-accept decisions become actions.
    """
    actions = []
    if not isinstance(judge_stage, dict):
        return actions
    for o in judge_stage.get("outputs") or []:
        res = (o or {}).get("result") or {}
        if not isinstance(res, dict):
            continue
        if res.get("needs_human"):
            actions.append({
                "type": "human_review",
                "priority": "critical",
                "description": "judge flagged needs_human",
            })
        for d in res.get("decisions", []):
            if not isinstance(d, dict):
                continue
            verdict = d.get("verdict")
            severity = d.get("severity")
            if verdict == "escalate":
                actions.append({
                    "type": "human_review",
                    "priority": "critical",
                    "description": "answer #%s escalated: %s"
                    % (d.get("id"), d.get("evidence") or ""),
                })
            elif verdict != "accept" and severity in ("critical", "major"):
                actions.append({
                    "type": "address_issue",
                    "priority": severity,
                    "description": "answer #%s %s (%s): %s"
                    % (d.get("id"), verdict, severity,
                       d.get("evidence") or ""),
                })
        break
    return _redact(actions)


def build_decision_object(record):
    """Build a Decision Object dict from a loaded run record dict.

    Fails soft: missing pieces become None/[] with notes, never raise.
    """
    if not isinstance(record, dict):
        raise ValueError("record must be a dict")

    stages = record.get("stages", {}) or {}
    panel_stage = stages.get("panel", {}) or {}
    judge_stage = stages.get("judge", {}) or {}

    panel_models = []
    for o in panel_stage.get("outputs", []) or []:
        if isinstance(o, dict) and o.get("model"):
            panel_models.append(o["model"])

    verdict_block = record.get("verdict") or {}
    verdict_text = verdict_block.get("text") if isinstance(
        verdict_block, dict) else str(verdict_block)

    confidence, factors = _confidence_from_judge(
        judge_stage, len(panel_models))

    obj = {
        "schema_version": SCHEMA_VERSION,
        "verdict": verdict_text,
        "confidence": confidence,
        "confidence_factors": factors,
        "disagreements": _disagreements_from_judge(
            judge_stage, panel_models),
        "evidence": _evidence_from_record(record),
        "actions": _actions_from_judge(judge_stage),
        "source_record_hash": record.get("record_hash"),
    }
    obj["decision_hash"] = _sha256_of(
        {k: v for k, v in obj.items() if k != "decision_hash"},
        schema_version=SCHEMA_VERSION)
    return obj


def validate_decision_object(obj):
    """Fail-closed validation. Returns (ok: bool, error: str|None)."""
    if not isinstance(obj, dict):
        return False, "not a JSON object"
    for f in ("schema_version", "verdict", "confidence",
              "disagreements", "evidence", "actions"):
        if f not in obj:
            return False, "missing field: %s" % f
    if obj.get("schema_version") != SCHEMA_VERSION:
        return False, "unsupported schema_version: %s" % obj.get(
            "schema_version")
    want = obj.get("decision_hash")
    got = _sha256_of(
        {k: v for k, v in obj.items() if k != "decision_hash"},
        schema_version=obj.get("schema_version", 1))
    if want != got:
        return False, "decision hash mismatch (want %s, got %s)" % (
            str(want)[:12], got[:12])
    return True, None


def main(argv):
    if len(argv) != 2:
        print("usage: python3 -m tt.decision_object <record.json>",
              file=sys.stderr)
        return 2
    from tt.run_record import load_record
    rec, err = load_record(argv[1])
    if err:
        print("error: %s" % err, file=sys.stderr)
        return 1
    obj = build_decision_object(rec)
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
