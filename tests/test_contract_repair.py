"""Tests for thinktank.py chat_json_repair (v0.16 behavior + v0.17 stats).

Covers the contract-repair retry contract:
- contract failure on call 1 -> call 2 is a REPAIR retry (failure reason
  fed back) with DOUBLE the token cap;
- empty/error reply on call 1 -> call 2 is a PLAIN retry (same messages)
  with DOUBLE the token cap;
- first-try success -> one call, stats mode "first-ok";
- two failures -> out, repaired False.
Stdlib unittest only; thinktank.chat is mocked, no network."""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import thinktank
from thinktank import chat_json_repair


def _parse(text):
    """Minimal judge-like contract: JSON object with a 'winner' key."""
    try:
        obj = json.loads(text)
    except Exception:
        return None, False, "no JSON"
    if isinstance(obj, dict) and "winner" in obj:
        return obj, True, ""
    return None, False, "contract violation"


def _chat(text="", error=None, finish_reason="stop", cost=0.01):
    return {"text": text, "usage": {}, "cost": cost, "error": error,
            "elapsed": 1.0, "truncated": finish_reason == "length",
            "finish_reason": finish_reason}


_MSGS = [{"role": "system", "content": "SYS"},
         {"role": "user", "content": "pick a winner"}]


class TestContractRepair(unittest.TestCase):
    def test_first_try_ok_single_call(self):
        stats = {}
        with mock.patch.object(thinktank, "chat",
                               return_value=_chat('{"winner": 1}')) as m:
            obj, last, repaired, total = chat_json_repair(
                "m", _MSGS, _parse, 800, 0.3, 120, "k", stats=stats)
        self.assertEqual(obj, {"winner": 1})
        self.assertFalse(repaired)
        self.assertEqual(m.call_count, 1)
        self.assertEqual(stats, {"attempts": 1, "mode": "first-ok",
                                 "first_failure": None})
        self.assertAlmostEqual(total, 0.01)

    def test_contract_failure_repair_retry_doubled_tokens(self):
        calls = []

        def fake_chat(model, msgs, max_tokens, temp, timeout, key):
            calls.append((list(msgs), max_tokens))
            if len(calls) == 1:
                return _chat("this is prose, not json")
            return _chat('{"winner": 0}')

        stats = {}
        with mock.patch.object(thinktank, "chat", side_effect=fake_chat):
            obj, last, repaired, total = chat_json_repair(
                "m", _MSGS, _parse, 800, 0.3, 120, "k", stats=stats)
        self.assertEqual(obj, {"winner": 0})
        self.assertTrue(repaired)
        self.assertEqual(len(calls), 2)
        first_msgs, first_tokens = calls[0]
        second_msgs, second_tokens = calls[1]
        self.assertEqual(first_tokens, 800)
        self.assertEqual(second_tokens, 1600)
        # Repair retry: previous reply + failure reason fed back.
        self.assertEqual(second_msgs[0], _MSGS[0])
        self.assertEqual(second_msgs[1], _MSGS[1])
        self.assertEqual(second_msgs[2]["role"], "assistant")
        self.assertIn("not json", second_msgs[2]["content"])
        self.assertIn("no JSON", second_msgs[3]["content"])
        self.assertEqual(stats["attempts"], 2)
        self.assertEqual(stats["mode"], "repair")
        self.assertEqual(stats["first_failure"], "no JSON")
        self.assertAlmostEqual(total, 0.02)

    def test_empty_reply_plain_retry_doubled_tokens(self):
        calls = []

        def fake_chat(model, msgs, max_tokens, temp, timeout, key):
            calls.append((list(msgs), max_tokens))
            if len(calls) == 1:
                return _chat("", finish_reason="")
            return _chat('{"winner": 2}')

        stats = {}
        with mock.patch.object(thinktank, "chat", side_effect=fake_chat):
            obj, last, repaired, total = chat_json_repair(
                "m", _MSGS, _parse, 800, 0.3, 120, "k", stats=stats)
        self.assertEqual(obj, {"winner": 2})
        self.assertTrue(repaired)
        self.assertEqual(len(calls), 2)
        # Plain retry: messages identical to call 1, no repair prompt.
        self.assertEqual(calls[1][0], calls[0][0])
        self.assertEqual(calls[1][1], 1600)
        self.assertEqual(stats["mode"], "retry")
        self.assertEqual(stats["first_failure"], "empty")

    def test_error_reply_plain_retry(self):
        calls = []

        def fake_chat(model, msgs, max_tokens, temp, timeout, key):
            calls.append(max_tokens)
            if len(calls) == 1:
                return _chat(error="HTTP 429: slow down", finish_reason="")
            return _chat('{"winner": 0}')

        stats = {}
        with mock.patch.object(thinktank, "chat", side_effect=fake_chat):
            obj, last, repaired, total = chat_json_repair(
                "m", _MSGS, _parse, 800, 0.3, 120, "k", stats=stats)
        self.assertEqual(obj, {"winner": 0})
        self.assertTrue(repaired)
        self.assertEqual(stats["mode"], "retry")
        self.assertEqual(stats["first_failure"], "HTTP 429: slow down")

    def test_two_failures_out(self):
        stats = {}
        with mock.patch.object(thinktank, "chat",
                               return_value=_chat("still prose")) as m:
            obj, last, repaired, total = chat_json_repair(
                "m", _MSGS, _parse, 800, 0.3, 120, "k", stats=stats)
        self.assertIsNone(obj)
        self.assertFalse(repaired)
        self.assertEqual(m.call_count, 2)
        self.assertEqual(stats["attempts"], 2)
        self.assertEqual(stats["mode"], "repair")

    def test_return_tuple_still_four_elements(self):
        with mock.patch.object(thinktank, "chat",
                               return_value=_chat('{"winner": 0}')):
            result = chat_json_repair("m", _MSGS, _parse, 800, 0.3, 120,
                                      "k")
        self.assertEqual(len(result), 4)


if __name__ == "__main__":
    unittest.main()
