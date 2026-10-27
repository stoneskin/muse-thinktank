"""Tests for thinktank.panel_call (v0.18).

One panel call with a single retry at double tokens, mirroring the
judge/critic repair-retry the panel never got. chat is mocked, no network.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import thinktank


def _result(text="", error=None, finish_reason="stop", cost=0.0):
    return {"text": text, "usage": {}, "cost": cost, "error": error,
            "elapsed": 1.0, "truncated": finish_reason == "length",
            "finish_reason": finish_reason}


class TestPanelCall(unittest.TestCase):
    def test_first_ok_single_call_with_floor(self):
        with mock.patch("thinktank.chat",
                        return_value=_result("answer")) as m:
            r = thinktank.panel_call("openai/gpt-5-mini", [], 800, 0.0,
                                     60, "key")
        self.assertEqual(r["text"], "answer")
        self.assertEqual(m.call_count, 1)
        # gpt-5-mini floor: 800 -> 4000.
        self.assertEqual(m.call_args[0][2], 4000)

    def test_empty_then_ok_retries_at_double_tokens(self):
        with mock.patch("thinktank.chat",
                        side_effect=[_result(""),
                                     _result("recovered")]) as m:
            r = thinktank.panel_call("some/model", [], 500, 0.0, 60, "key")
        self.assertEqual(r["text"], "recovered")
        self.assertEqual(m.call_count, 2)
        self.assertEqual(m.call_args[0][2], 1000)

    def test_truncated_then_ok_retries(self):
        with mock.patch("thinktank.chat",
                        side_effect=[_result("partial",
                                             finish_reason="length"),
                                     _result("full")]) as m:
            r = thinktank.panel_call("some/model", [], 500, 0.0, 60, "key")
        self.assertEqual(r["text"], "full")
        self.assertEqual(m.call_count, 2)

    def test_both_fail_keeps_first_partial_text(self):
        with mock.patch("thinktank.chat",
                        side_effect=[_result("partial",
                                             finish_reason="length"),
                                     _result("")]) as m:
            r = thinktank.panel_call("some/model", [], 500, 0.0, 60, "key")
        self.assertEqual(r["text"], "partial")
        self.assertEqual(m.call_count, 2)

    def test_both_fail_empty_returns_second(self):
        with mock.patch("thinktank.chat",
                        side_effect=[_result(""), _result("")]) as m:
            r = thinktank.panel_call("some/model", [], 500, 0.0, 60, "key")
        self.assertEqual(r["text"], "")
        self.assertEqual(m.call_count, 2)


if __name__ == "__main__":
    unittest.main()
