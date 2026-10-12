"""v0.4 module: tt/members.py."""

import json
import os
from .util import log

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
        log("member-state save failed: %s" % exc)


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
            log("member selected: %s passed (capability %.2f x availability %.2f = %.2f)"
                % (m, cap, avail, score))
        else:
            dropped.append(m)
            log("member dropped: %s (%.2f < %.2f)" % (m, score, MEMBER_MIN_SCORE))
    return kept, dropped
