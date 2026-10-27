#!/usr/bin/env python3
"""v0.16 fault-injection tests for the thinktank harness.

These pin the failure modes of the 2026-10-21 red-team review run
(and the older judge contract violations) as offline regression tests:

  1. critic returns non-JSON once  -> repair retry recovers it
  2. critic fails twice            -> backup substitute is promoted
  3. every critic fails            -> run stays fail-closed (exit 2)
  4. truncated panel answer wins   -> confidence capped + gate note
  5. chat_json_repair unit check   -> obj + repaired flag + cost sum
  6. first reply empty (starved)   -> plain retry recovers the role

No API calls: thinktank.chat is replaced by a scripted fake.
Run: python3 scripts/test_stability.py   (exit 0 = all pass)
"""

import contextlib
import importlib.util
import io
import json
import os
import sys
import threading
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

spec = importlib.util.spec_from_file_location(
    "thinktank", os.path.join(ROOT, "thinktank.py"))
tt_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tt_mod)

CRITIC_OK = json.dumps({"findings": [
    {"severity": "major", "category": "logical",
     "line": "some line", "attack": "some attack"}]})
ADJ_OK = json.dumps({
    "verdict": "revise",
    "findings": [{"severity": "major", "category": "logical",
                  "line": "some line", "attack": "some attack",
                  "keep": True}],
    "summary": "draft needs work", "confidence": "high"})


def resp(text):
    return {"text": text, "cost": 0.001, "error": None,
            "truncated": False, "usage": {"total_tokens": 10},
            "elapsed": 0.01, "finish_reason": "stop"}


class FakeChat:
    """model -> list of reply texts; each call pops the next reply,
    the last one repeats. Thread-safe (critics run in parallel)."""

    def __init__(self, scripts):
        self.scripts = {m: list(v) for m, v in scripts.items()}
        self.lock = threading.Lock()
        self.calls = []

    def __call__(self, model, messages, max_tokens, temperature,
                 timeout, key):
        with self.lock:
            self.calls.append(model)
            seq = self.scripts.get(model, [""])
            text = seq.pop(0) if len(seq) > 1 else seq[0]
        return resp(text)


def make_args(**over):
    a = types.SimpleNamespace(
        critic_models=None, models="m1,m2", max_tokens=800,
        panel_timeout=5, budget=2.0, judge_model="adj",
        member_state=None)
    for k, v in over.items():
        setattr(a, k, v)
    return a


def run_redteam_capture(a, backups=None, truncated=False):
    buf = io.StringIO()
    code = None
    with contextlib.redirect_stdout(buf):
        try:
            # v0.17: run_redteam returns (code, spent), not bare code.
            code, _spent = tt_mod.run_redteam(
                a, "a draft worth attacking", None, {}, 0.0, 0.0,
                "the question", critic_backups=backups,
                draft_truncated=truncated)
        except SystemExit as e:
            code = e.code
    return code, buf.getvalue()


FAILURES = []


def check(name, cond, detail=""):
    print("%s %s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAILURES.append(name)


def test_repair_recovers_critic():
    fake = FakeChat({
        "flaky": ["definitely not json", CRITIC_OK],
        "good": [CRITIC_OK],
        "adj": [ADJ_OK],
    })
    tt_mod.chat = fake
    a = make_args(critic_models="flaky,good", models="flaky,good")
    code, out = run_redteam_capture(a)
    check("repair: exit 0", code == 0, "got %r" % code)
    check("repair: report printed", "RED TEAM REPORT" in out)
    check("repair: completeness shows 1 repaired",
          "1 repaired" in out, out.splitlines()[1] if out else "")
    check("repair: flaky called twice", fake.calls.count("flaky") == 2)


def test_substitution():
    fake = FakeChat({
        "hopeless": ["garbage", "still garbage"],
        "good": [CRITIC_OK],
        "sub": [CRITIC_OK],
        "adj": [ADJ_OK],
    })
    tt_mod.chat = fake
    a = make_args(critic_models="hopeless,good", models="hopeless,good")
    code, out = run_redteam_capture(a, backups=["sub"])
    check("substitute: exit 0", code == 0, "got %r" % code)
    check("substitute: completeness shows 1 substitutes",
          "1 substitutes" in out)
    check("substitute: sub was called", "sub" in fake.calls)


def test_fail_closed_when_all_down():
    fake = FakeChat({
        "hopeless": ["garbage"],
        "adj": [ADJ_OK],
    })
    tt_mod.chat = fake
    a = make_args(critic_models="hopeless", models="hopeless")
    code, _out = run_redteam_capture(a, backups=[])
    check("fail-closed: exit 2", code == 2, "got %r" % code)


def test_truncation_gate():
    judge = {"winner": 0, "confidence": "high", "decisions": []}
    answers = [{"model": "m", "text": "t", "truncated": True}]
    note = tt_mod.truncation_gate(judge, answers)
    check("gate: note produced", note is not None)
    check("gate: confidence capped to medium",
          judge["confidence"] == "medium")
    judge2 = {"winner": 0, "confidence": "high", "decisions": []}
    answers2 = [{"model": "m", "text": "t", "truncated": False}]
    note2 = tt_mod.truncation_gate(judge2, answers2)
    check("gate: intact winner untouched",
          note2 is None and judge2["confidence"] == "high")


def test_helper_direct():
    fake = FakeChat({"m": ["oops", CRITIC_OK]})
    tt_mod.chat = fake
    obj, _r, repaired, cost = tt_mod.chat_json_repair(
        "m", [{"role": "user", "content": "x"}], tt_mod._parse_critic,
        800, 0.7, 5, None, role="critic")
    check("helper: obj parsed", obj is not None)
    check("helper: repaired flag", repaired is True)
    check("helper: cost sums both calls", abs(cost - 0.002) < 1e-9)


def test_empty_first_reply_recovers():
    # 2026-10-21 live shape: reasoning judge starved by the token cap
    # returned empty on call 1; a plain retry must recover the role.
    fake = FakeChat({"m": ["", CRITIC_OK]})
    tt_mod.chat = fake
    obj, _r, repaired, _cost = tt_mod.chat_json_repair(
        "m", [{"role": "user", "content": "x"}], tt_mod._parse_critic,
        800, 0.7, 5, None, role="critic")
    check("empty-first: obj parsed", obj is not None)
    check("empty-first: repaired flag", repaired is True)
    check("empty-first: exactly 2 calls", len(fake.calls) == 2)


def main():
    test_repair_recovers_critic()
    test_substitution()
    test_fail_closed_when_all_down()
    test_truncation_gate()
    test_helper_direct()
    test_empty_first_reply_recovers()
    if FAILURES:
        print("\n%d check(s) FAILED: %s" % (len(FAILURES), FAILURES))
        return 1
    print("\nall stability checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
