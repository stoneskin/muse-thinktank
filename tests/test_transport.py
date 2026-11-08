"""Unit tests for tt/transport.py chat() — stdlib unittest only.

urllib is fully stubbed with unittest.mock: no real network traffic,
no real API key. The key passed in is a dummy string.
"""

import datetime
import io
import json
import os
import tempfile
import unittest
import urllib.error
from unittest import mock

from tt.transport import chat, free_ids


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


class TestFreeIds(unittest.TestCase):
    """Regression: free_ids() referenced two undefined names (2026-11-04).

    The cached-report path used dt.datetime with no datetime import,
    and the live-fetch path used CATALOG with no such constant, so
    --free-only crashed before the estimate on both branches.
    """

    def _write_report(self, checked_at, ids):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"checked_at": checked_at,
                       "free": [{"id": m} for m in ids]}, f)
        self.addCleanup(os.unlink, path)
        return path

    def test_fresh_cached_report_returns_exact_ids(self):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        path = self._write_report(
            now, ["stealth/crouton-alpha", "a/b:free"])
        self.assertEqual(
            free_ids(path), {"stealth/crouton-alpha", "a/b:free"})

    def test_live_fetch_filters_zero_priced(self):
        catalog = {"data": [
            {"id": "stealth/crouton-alpha",
             "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "paid/model",
             "pricing": {"prompt": "0.30", "completion": "2.40"}},
            {"id": "no-pricing/model"},
        ]}
        with mock.patch("tt.transport.urllib.request.urlopen",
                        return_value=_fake_response(catalog)) as urlopen_mock:
            result = free_ids(None)
        self.assertEqual(result, {"stealth/crouton-alpha"})
        req = urlopen_mock.call_args[0][0]
        self.assertIn("openrouter.ai/api/v1/models", req.full_url)

    def test_stale_cached_report_falls_back_to_live_fetch(self):
        stale = (datetime.datetime.now(datetime.timezone.utc)
                 - datetime.timedelta(hours=25)).isoformat()
        path = self._write_report(stale, ["old/model:free"])
        catalog = {"data": [
            {"id": "stealth/crouton-alpha",
             "pricing": {"prompt": "0", "completion": "0"}},
        ]}
        with mock.patch("tt.transport.urllib.request.urlopen",
                        return_value=_fake_response(catalog)):
            result = free_ids(path)
        self.assertEqual(result, {"stealth/crouton-alpha"})


if __name__ == "__main__":
    unittest.main()
