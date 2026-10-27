"""Unit tests for tt/context.py load_context_data() / sanitize_context().

stdlib unittest only; all files live in tempfile directories.
"""

import json
import os
import tempfile
import unittest

from tt.context import load_context_data, sanitize_context


def _write(tmpdir, name, content):
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


class TestLoadContextData(unittest.TestCase):
    def test_valid_json_with_preamble_and_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "ctx.json", json.dumps({
                "preamble": "as of 2026-10-26",
                "facts": {"price": 123.45, "ticker": "XYZ"},
            }))
            data = load_context_data(path)
        self.assertNotIn("__error__", data)
        self.assertEqual(data["preamble"], "as of 2026-10-26")
        self.assertEqual(data["facts"], {"price": 123.45, "ticker": "XYZ"})

    def test_no_path_returns_none(self):
        self.assertIsNone(load_context_data(None))
        self.assertIsNone(load_context_data(""))

    def test_missing_file_returns_error_dict(self):
        data = load_context_data("/nonexistent-dir-xyz/ctx.json")
        self.assertIn("__error__", data)
        self.assertIn("not found", data["__error__"])

    def test_invalid_json_returns_error_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "bad.json", "{not json")
            data = load_context_data(path)
        self.assertIn("__error__", data)
        self.assertIn("unreadable", data["__error__"])

    def test_non_object_json_returns_error_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "list.json", "[1, 2, 3]")
            data = load_context_data(path)
        self.assertIn("__error__", data)

    def test_empty_facts_returns_error_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "empty.json", json.dumps({
                "preamble": "x", "facts": {}}))
            data = load_context_data(path)
        self.assertIn("__error__", data)
        self.assertIn("empty facts", data["__error__"])

    def test_missing_facts_returns_error_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, "nofacts.json", json.dumps({
                "preamble": "x"}))
            data = load_context_data(path)
        self.assertIn("__error__", data)


class TestSanitizeContext(unittest.TestCase):
    def test_short_payload_not_truncated(self):
        out = sanitize_context({"preamble": "p", "as_of": "today",
                                "facts": {"a": 1}})
        self.assertNotIn("[truncated]", out)
        self.assertIn('"a":1', out)
        # Delimiters must match: open and close share the same token.
        self.assertIn("<<<CONTEXT_DATA:", out)
        self.assertIn("<<<END_CONTEXT:", out)

    def test_oversize_payload_truncated_to_8000_chars_with_marker(self):
        big = "x" * 20000
        out = sanitize_context({"preamble": "", "as_of": "",
                                "facts": {"blob": big}})
        self.assertIn("\u2026[truncated]", out)
        # The full 20000-char blob must not survive intact.
        self.assertNotIn(big, out)
        # The payload line between the two delimiter lines is exactly
        # 8000 chars plus the truncation marker. Output shape:
        # "", "<<<CONTEXT_DATA:...>>>", payload, "<<<END_CONTEXT:...>>>", ""
        payload = out.split("\n")[2]
        self.assertTrue(payload.endswith("\u2026[truncated]"))
        self.assertEqual(len(payload) - len("\u2026[truncated]"), 8000)


if __name__ == "__main__":
    unittest.main()
