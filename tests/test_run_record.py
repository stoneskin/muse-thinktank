"""Unit tests for tt/run_record.py save() / load_record().

stdlib unittest only; all records live in tempfile directories.
load_record() fail-closes: it returns (None, error) rather than raising
for a missing file, bad JSON, missing required fields, or hash mismatch.
"""

import json
import os
import tempfile
import unittest

from tt.run_record import RunRecord, load_record


def _make_record():
    rec = RunRecord("Is this plan sound?",
                    context_data={"preamble": "as of today",
                                  "facts": {"price": 10.0}})
    rec.set_params(max_tokens=500)
    rec.add_model("panel", "some/model:free")
    rec.add_stage("panel", outputs=["opinion A"], cost=0.0)
    rec.add_cost(0.001)
    rec.set_verdict("yes, with caveats", evidence_refs=["panel"])
    return rec


class TestSaveLoadRoundTrip(unittest.TestCase):
    def test_save_then_load_returns_same_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "run.json")
            _make_record().save(path)
            record, error = load_record(path)
        self.assertIsNone(error)
        self.assertIsNotNone(record)
        self.assertEqual(record["question"], "Is this plan sound?")
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["verdict"]["text"],
                         "yes, with caveats")
        self.assertEqual(record["models"]["panel"]["id"],
                         "some/model:free")
        self.assertIn("record_hash", record)
        self.assertAlmostEqual(record["cost"]["spent"], 0.001)

    def test_save_returns_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "run.json")
            self.assertEqual(_make_record().save(path), path)
            self.assertTrue(os.path.exists(path))


class TestLoadValidation(unittest.TestCase):
    def test_tampered_content_fails_hash_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "run.json")
            _make_record().save(path)
            with open(path) as f:
                data = json.load(f)
            data["question"] = "A totally different question"
            with open(path, "w") as f:
                json.dump(data, f)
            record, error = load_record(path)
        self.assertIsNone(record)
        self.assertIsNotNone(error)
        self.assertIn("hash mismatch", error)

    def test_tampered_cost_fails_hash_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "run.json")
            _make_record().save(path)
            with open(path) as f:
                data = json.load(f)
            data["cost"]["spent"] = 999.0
            with open(path, "w") as f:
                json.dump(data, f)
            record, error = load_record(path)
        self.assertIsNone(record)
        self.assertIn("hash mismatch", error)

    def test_missing_required_field_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "run.json")
            _make_record().save(path)
            with open(path) as f:
                data = json.load(f)
            del data["verdict"]
            with open(path, "w") as f:
                json.dump(data, f)
            record, error = load_record(path)
        self.assertIsNone(record)
        self.assertIsNotNone(error)
        self.assertIn("missing required fields", error)
        self.assertIn("verdict", error)

    def test_missing_file_fails(self):
        record, error = load_record("/nonexistent-dir-xyz/run.json")
        self.assertIsNone(record)
        self.assertIn("not found", error)

    def test_invalid_json_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "bad.json")
            with open(path, "w") as f:
                f.write("{not json")
            record, error = load_record(path)
        self.assertIsNone(record)
        self.assertIn("unreadable", error)

    def test_non_object_json_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "list.json")
            with open(path, "w") as f:
                f.write("[1, 2]")
            record, error = load_record(path)
        self.assertIsNone(record)
        self.assertIn("not a JSON object", error)


if __name__ == "__main__":
    unittest.main()
