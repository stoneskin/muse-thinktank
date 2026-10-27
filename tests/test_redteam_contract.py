"""Contract test for thinktank.run_redteam's return type.

Regression pin for a review finding on the superseded public PR #21
(reviewer wsun4ipipeline): v0.17 changed run_redteam to return
(code, spent), but scripts/test_stability.py kept treating the result
as a bare int — a tuple is never == 0, and '"got %r" % code' raises
TypeError. The script is not part of `python -m unittest discover`,
so the regression was invisible to the 73-test run. This test pins
the 2-tuple contract inside the unittest suite so the class of
regression is caught automatically. The standalone script keeps its
own harness (deliberately not folded in); its call site was fixed
separately to unpack the tuple.

Stdlib unittest only; thinktank.chat is mocked, no network.
"""

import contextlib
import io
import json
import os
import sys
import threading
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import thinktank

CRITIC_OK = json.dumps({"findings": [
    {"severity": "major", "category": "logical",
     "line": "some line", "attack": "some attack"}]})
ADJ_OK = json.dumps({
    "verdict": "revise",
    "findings": [{"severity": "major", "category": "logical",
                  "line": "some line", "attack": "some attack",
                  "keep": True}],
    "summary": "draft needs work", "confidence": "high"})


def _resp(text):
    return {"text": text, "cost": 0.001, "error": None,
            "truncated": False, "usage": {"total_tokens": 10},
            "elapsed": 0.01, "finish_reason": "stop"}


class FakeChat:
    """model -> list of reply texts; each call pops the next reply,
    the last one repeats. Thread-safe (critics run in parallel)."""

    def __init__(self, scripts):
        self.scripts = {m: list(v) for m, v in scripts.items()}
        self.lock = threading.Lock()

    def __call__(self, model, messages, max_tokens, temperature,
                 timeout, key):
        with self.lock:
            seq = self.scripts.get(model, [""])
            text = seq.pop(0) if len(seq) > 1 else seq[0]
        return _resp(text)


def _args(**over):
    a = types.SimpleNamespace(
        critic_models=None, models="m1,m2", max_tokens=800,
        panel_timeout=5, budget=2.0, judge_model="adj",
        member_state=None)
    for k, v in over.items():
        setattr(a, k, v)
    return a


class TestRunRedteamContract(unittest.TestCase):
    def _run(self, scripts):
        thinktank.chat = FakeChat(scripts)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            return thinktank.run_redteam(
                _args(), "a draft worth attacking", None, {}, 0.0, 0.0,
                "the question")

    def test_returns_code_and_spent_tuple(self):
        result = self._run({"m1": [CRITIC_OK], "m2": [CRITIC_OK],
                            "adj": [ADJ_OK]})
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        code, spent = result
        self.assertEqual(code, 0)
        self.assertIsInstance(spent, float)
        self.assertGreater(spent, 0.0)

    def test_all_critics_fail_raises_system_exit(self):
        # Fail-closed path is preserved: no usable critic output
        # raises SystemExit(2) instead of returning a tuple.
        with self.assertRaises(SystemExit) as cm:
            self._run({"m1": [""], "m2": [""], "adj": [ADJ_OK]})
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
