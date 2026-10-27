"""Unit tests for tt/transport.py chat() — stdlib unittest only.

urllib is fully stubbed with unittest.mock: no real network traffic,
no real API key. The key passed in is a dummy string.
"""

import io
import json
import unittest
import urllib.error
from unittest import mock

from tt.transport import chat


def _fake_response(payload):
    """A context manager whose __enter__ returns a json.load-able stream."""
    resp = mock.MagicMock()
    resp.__enter__.return_value = io.StringIO(json.dumps(payload))
    resp.__exit__.return_value = False
    return resp


def _run_chat(payload):
    with mock.patch("tt.transport.urllib.request.urlopen",
                    return_value=_fake_response(payload)) as urlopen_mock:
        result = chat("dummy/model:free",
                      [{"role": "user", "content": "hi"}],
                      100, 0.0, 30, "dummy-key-not-real")
    urlopen_mock.assert_called_once()
    return result


class TestChatSuccess(unittest.TestCase):
    def test_success_returns_text_usage_cost_not_truncated(self):
        result = _run_chat({
            "choices": [{"message": {"content": "  hello world  "},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                      "cost": 0.0123},
        })
        self.assertEqual(result["text"], "hello world")
        self.assertEqual(result["usage"]["prompt_tokens"], 10)
        self.assertAlmostEqual(result["cost"], 0.0123)
        self.assertIsNone(result["error"])
        self.assertFalse(result["truncated"])
        self.assertEqual(result["finish_reason"], "stop")

    def test_empty_content_gives_empty_text_and_no_error(self):
        result = _run_chat({
            "choices": [{"message": {"content": ""},
                         "finish_reason": "stop"}],
            "usage": {},
        })
        self.assertEqual(result["text"], "")
        self.assertIsNone(result["error"])
        self.assertFalse(result["truncated"])

    def test_no_choices_gives_empty_text_and_no_error(self):
        result = _run_chat({"choices": [], "usage": {}})
        self.assertEqual(result["text"], "")
        self.assertIsNone(result["error"])
        self.assertEqual(result["finish_reason"], "")


class TestChatErrors(unittest.TestCase):
    def test_http_error(self):
        err = urllib.error.HTTPError(
            "https://example.invalid/", 429, "Too Many Requests", {},
            fp=io.BytesIO(b"rate limited"))
        with mock.patch("tt.transport.urllib.request.urlopen",
                        side_effect=err):
            result = chat("dummy/model:free",
                          [{"role": "user", "content": "hi"}],
                          100, 0.0, 30, "dummy-key-not-real")
        self.assertEqual(result["text"], "")
        self.assertEqual(result["cost"], 0.0)
        self.assertFalse(result["truncated"])
        self.assertTrue(result["error"].startswith("HTTP 429: "),
                        result["error"])
        self.assertIn("rate limited", result["error"])

    def test_api_error_body(self):
        result = _run_chat({
            "error": {"message": "invalid key", "code": 401},
        })
        self.assertEqual(result["text"], "")
        self.assertTrue(result["error"].startswith("API: "),
                        result["error"])
        self.assertIn("invalid key", result["error"])
        self.assertFalse(result["truncated"])

    def test_network_error(self):
        with mock.patch("tt.transport.urllib.request.urlopen",
                        side_effect=ConnectionError("boom")):
            result = chat("dummy/model:free",
                          [{"role": "user", "content": "hi"}],
                          100, 0.0, 30, "dummy-key-not-real")
        self.assertTrue(result["error"].startswith("network: "),
                        result["error"])


class TestChatTruncation(unittest.TestCase):
    def test_finish_reason_length_sets_truncated(self):
        result = _run_chat({
            "choices": [{"message": {"content": "partial"},
                         "finish_reason": "length"}],
            "usage": {"cost": 0.0},
        })
        self.assertEqual(result["text"], "partial")
        self.assertTrue(result["truncated"])
        self.assertEqual(result["finish_reason"], "length")
        self.assertIsNone(result["error"])


if __name__ == "__main__":
    unittest.main()
