"""Tests for tt/runlog.py (v0.17): per-run JSON diagnostic logs and
90-day pruning. Stdlib unittest only; no network, no API keys."""

import io
import json
import os
import re
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tt.runlog import (FILENAME_RE, RETENTION_DAYS, RunLog, default_log_dir,
                       prune_logs)


def _mklog(tmpdir, params=None):
    return RunLog(tmpdir, params or {"question_length": 5})


class TestRunLogFilename(unittest.TestCase):
    def test_filename_matches_own_pattern(self):
        with tempfile.TemporaryDirectory() as d:
            rl = _mklog(d)
            self.assertRegex(rl.filename, FILENAME_RE)
            self.assertEqual(rl.path, os.path.join(d, rl.filename))

    def test_run_id_is_8_hex_chars(self):
        with tempfile.TemporaryDirectory() as d:
            rl = _mklog(d)
            self.assertRegex(rl.run_id, r"^[0-9a-f]{8}$")

    def test_two_logs_in_same_second_do_not_collide(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = _mklog(d), _mklog(d)
            self.assertNotEqual(a.run_id, b.run_id)
            self.assertNotEqual(a.filename, b.filename)

    def test_default_log_dir_is_outside_repo(self):
        self.assertEqual(default_log_dir(),
                         os.path.expanduser("~/workspace/thinktank-logs"))


class TestRunLogWrite(unittest.TestCase):
    def test_write_creates_json_with_key_fields(self):
        with tempfile.TemporaryDirectory() as d:
            rl = _mklog(d, {"tier": "free", "question_length": 12})
            rl.set_estimate(0.0, None, 2.0)
            rl.set_context(None, 0, 0)
            rl.set_member_selection(["a", "b"], ["a", "b"], [])
            rl.add_health_check("pre-panel", [
                {"model": "m1", "ok": False, "error": "HTTP 404: x",
                 "finish_reason": "", "elapsed": 1.2, "cost": 0.0,
                 "attempts": 2}])
            rl.add_panel([{"model": "m1", "text": "hello", "ok": True,
                           "error": None, "finish_reason": "stop",
                           "truncated": False,
                           "usage": {"prompt_tokens": 20,
                                     "completion_tokens": 135,
                                     "reasoning_tokens": 100,
                                     "total_tokens": 155},
                           "elapsed": 3.3, "cost": 0.0}])
            rl.set_judge([{"model": "j", "winner": 0, "confidence": "high",
                           "repaired": False, "attempts": 1, "mode": "first-ok",
                           "error": None, "finish_reason": "stop",
                           "cost": 0.0}], True, "", 0.0)
            rl.set_synth("j", True, None, "stop", 0.0, 151)
            rl.set_verdict("full verdict text", "synth")
            rl.set_spent(0.0)
            rl.mark("completed", "synth")
            path = rl.write()
            self.assertEqual(path, rl.path)
            data = json.load(open(path))
            self.assertEqual(data["run_id"], rl.run_id)
            self.assertEqual(data["status"], "completed")
            self.assertEqual(data["last_phase"], "synth")
            self.assertEqual(data["verdict"], "full verdict text")
            self.assertEqual(data["verdict_source"], "synth")
            self.assertEqual(data["panel"][0]["reasoning_tokens"], 100)
            self.assertEqual(data["panel"][0]["text_length"], 5)
            self.assertEqual(data["judge"]["models"][0]["attempts"], 1)
            self.assertEqual(data["judge"]["models"][0]["repair_mode"],
                             "first-ok")
            self.assertEqual(data["health_checks"][0]["models"][0]["error"],
                             "HTTP 404: x")
            self.assertEqual(data["health_checks"][0]["models"][0]["attempts"],
                             2)
            # No question text, no secrets anywhere in the log.
            blob = json.dumps(data)
            self.assertNotIn("Authorization", blob)
            self.assertNotIn("Bearer", blob)

    def test_write_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            rl = _mklog(d)
            p1 = rl.write()
            p2 = rl.write()
            self.assertEqual(p1, p2)
            self.assertTrue(rl.written)

    def test_error_summary_capped_at_300_chars(self):
        with tempfile.TemporaryDirectory() as d:
            rl = _mklog(d)
            rl.add_panel([{"model": "m", "text": "", "ok": False,
                           "error": "x" * 500, "finish_reason": None,
                           "truncated": False, "usage": {},
                           "elapsed": 1.0, "cost": 0.0}])
            rl.write()
            data = json.load(open(rl.path))
            err = data["panel"][0]["error"]
            self.assertTrue(err.endswith("...[truncated]"))
            self.assertLessEqual(len(err), 320)

    def test_write_failure_never_raises_one_stderr_warning(self):
        with tempfile.TemporaryDirectory() as d:
            blocker = os.path.join(d, "not-a-dir")
            with open(blocker, "w") as f:
                f.write("x")
            rl = RunLog(os.path.join(blocker, "sub"), {})
            buf = io.StringIO()
            with redirect_stderr(buf):
                result = rl.write()
            self.assertIsNone(result)
            self.assertFalse(rl.written)
            self.assertEqual(buf.getvalue().count("WARNING"), 1)


class TestPruneLogs(unittest.TestCase):
    def _touch(self, path, age_days):
        with open(path, "w") as f:
            f.write("{}")
        old = time.time() - age_days * 86400
        os.utime(path, (old, old))

    def test_deletes_only_old_own_pattern_files(self):
        with tempfile.TemporaryDirectory() as d:
            recent_own = os.path.join(
                d, "thinktank-20261027T040000Z-aaaaaaaa.json")
            old_own = os.path.join(
                d, "thinktank-20260801T000000Z-bbbbbbbb.json")
            old_other = os.path.join(d, "notes-20200101.txt")
            recent_other = os.path.join(d, "transcript.txt")
            self._touch(recent_own, 1)
            self._touch(old_own, 91)
            self._touch(old_other, 365)
            self._touch(recent_other, 0)
            deleted = prune_logs(d)
            self.assertEqual(deleted, 1)
            self.assertTrue(os.path.exists(recent_own))
            self.assertFalse(os.path.exists(old_own))
            self.assertTrue(os.path.exists(old_other))
            self.assertTrue(os.path.exists(recent_other))

    def test_boundary_90_days_kept_91_deleted(self):
        with tempfile.TemporaryDirectory() as d:
            keep = os.path.join(d, "thinktank-20261027T040000Z-cccccccc.json")
            drop = os.path.join(d, "thinktank-20261027T040000Z-dddddddd.json")
            self._touch(keep, 89)
            self._touch(drop, 91)
            self.assertEqual(prune_logs(d, days=90), 1)
            self.assertTrue(os.path.exists(keep))
            self.assertFalse(os.path.exists(drop))

    def test_retention_default_is_90(self):
        self.assertEqual(RETENTION_DAYS, 90)

    def test_missing_dir_returns_zero(self):
        self.assertEqual(prune_logs("/nonexistent-dir-xyz"), 0)

    def test_tmp_files_never_deleted(self):
        # write() uses a .tmp staging file; a stale one must survive prune.
        with tempfile.TemporaryDirectory() as d:
            tmp = os.path.join(
                d, "thinktank-20260801T000000Z-eeeeeeee.json.tmp")
            self._touch(tmp, 200)
            self.assertEqual(prune_logs(d), 0)
            self.assertTrue(os.path.exists(tmp))


if __name__ == "__main__":
    unittest.main()
