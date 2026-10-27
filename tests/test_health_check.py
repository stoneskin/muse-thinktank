"""Tests for tt/transport.py health_check (v0.17 signature).

health_check now returns (alive, spent, details) instead of (alive,
spent): per-model details carry ok/error/finish_reason/elapsed/cost so
a provider-side failure is distinguishable from a plain empty reply.
Stdlib unittest only; chat is mocked, no network."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tt.transport import health_check


def _chat_result(text="", error=None, finish_reason="stop", cost=0.0,
                 elapsed=1.0):
    return {"text": text, "usage": {}, "cost": cost, "error": error,
            "elapsed": elapsed, "truncated": finish_reason == "length",
            "finish_reason": finish_reason}


class TestHealthCheck(unittest.TestCase):
    def test_normal_reply_kept_with_details(self):
        with mock.patch("tt.transport.chat",
                        return_value=_chat_result("ok")) as m:
            alive, spent, details = health_check(["model-a"], "key")
        self.assertEqual(alive, ["model-a"])
        self.assertEqual(spent, 0.0)
        self.assertEqual(len(details), 1)
        d = details[0]
        self.assertEqual(d["model"], "model-a")
        self.assertTrue(d["ok"])
        self.assertIsNone(d["error"])
        self.assertEqual(d["finish_reason"], "stop")
        self.assertEqual(d["elapsed"], 1.0)
        # Probe prompt is the single-word ok ping.
        sent = m.call_args[0][1]
        self.assertEqual(sent, [{"role": "user",
                                 "content": "Reply with the single word: ok"}])

    def test_empty_reply_dropped_error_none(self):
        with mock.patch("tt.transport.chat",
                        return_value=_chat_result("", finish_reason="")):
            alive, spent, details = health_check(["model-a"], "key")
        self.assertEqual(alive, [])
        self.assertFalse(details[0]["ok"])
        self.assertIsNone(details[0]["error"])
        self.assertEqual(details[0]["finish_reason"], "")

    def test_length_truncation_recorded_not_collapsed_to_empty(self):
        # The 2026-10-26 gap: a reasoning model starving on the 50-token
        # probe looks like "empty response" unless finish_reason survives.
        with mock.patch("tt.transport.chat",
                        return_value=_chat_result("", finish_reason="length")):
            alive, spent, details = health_check(["model-a"], "key")
        self.assertEqual(alive, [])
        self.assertFalse(details[0]["ok"])
        self.assertEqual(details[0]["finish_reason"], "length")

    def test_http_error_preserved_verbatim(self):
        err = "HTTP 404: {\"error\": \"Not found\"}"
        with mock.patch("tt.transport.chat",
                        return_value=_chat_result(error=err,
                                                  finish_reason="")):
            alive, spent, details = health_check(["model-a"], "key")
        self.assertEqual(alive, [])
        self.assertEqual(details[0]["error"], err)

    def test_mixed_panel_and_cost_sum(self):
        def fake_chat(model, *args, **kwargs):
            if model == "good":
                return _chat_result("ok", cost=0.01, elapsed=0.5)
            return _chat_result(error="HTTP 429: slow down", cost=0.02,
                                finish_reason="")
        with mock.patch("tt.transport.chat", side_effect=fake_chat):
            alive, spent, details = health_check(["good", "bad"], "key")
        self.assertEqual(alive, ["good"])
        self.assertAlmostEqual(spent, 0.03)
        self.assertEqual([d["model"] for d in details], ["good", "bad"])
        self.assertTrue(details[0]["ok"])
        self.assertFalse(details[1]["ok"])

    def test_returns_three_tuple(self):
        with mock.patch("tt.transport.chat",
                        return_value=_chat_result("ok")):
            result = health_check(["m"], "key")
        self.assertEqual(len(result), 3)


if __name__ == "__main__":
    unittest.main()
