"""Regression coverage for the failed-run aggregate's missing-message handling."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "notes/failed-agent-runs/measure.py"
spec = importlib.util.spec_from_file_location("failed_run_measure", SCRIPT)
measure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measure)


class FailedRunMeasureTest(unittest.TestCase):
    def test_missing_messages_and_ordered_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs, index = root / "runs.db", root / "index.db"
            with sqlite3.connect(runs) as db:
                db.executescript("""
                    CREATE TABLE job_runs (workspace_id, run_id, job_id, state, created_at, input_json);
                    CREATE TABLE job_run_steps (workspace_id, run_id, step_index, state, error_message);
                """)
                for i in range(6):
                    db.execute("INSERT INTO job_runs VALUES (?, ?, ?, ?, ?, ?)",
                               ("fixture", str(i), "task_pr_pipeline", "failed",
                                "2026-08-01T00:00:00Z", "{}"))
                for i, message in enumerate((None, "", "\n", "unmatched error",
                                             "nothing to commit; provider exited"), start=1):
                    db.execute("INSERT INTO job_run_steps VALUES (?, ?, ?, ?, ?)",
                               ("fixture", str(i), 0, "failed", message))
            with sqlite3.connect(index) as db:
                db.executescript("""
                    CREATE TABLE task_bundle_bindings (workspace_id, task_id, canonical_path);
                    CREATE TABLE task_bundle_index (workspace_id, task_id, created_at);
                    CREATE TABLE task_bundle_tags (workspace_id, task_id, tag);
                    CREATE TABLE task_bundle_relations (workspace_id, source_task_id, target_task_id, relation_type);
                """)
            before = [hashlib.sha256(path.read_bytes()).digest() for path in (runs, index)]
            output = subprocess.check_output([
                sys.executable, "-B", str(SCRIPT), "--run-db", str(runs),
                "--task-index", str(index), "--workspace", "fixture",
                "--since", "2026-07-01T00:00:00Z", "--until", "2026-09-01T00:00:00Z",
                "--cutoff", "2026-09-01T00:00:00Z",
            ], text=True)
            failed = json.loads(output)["failed"]
            self.assertEqual(failed["total"], 6)
            self.assertEqual(failed["without_failed_step_message"], 4)
            self.assertEqual(failed["by_category"], {"orbit_defect": 5, "no_change_to_ship": 1})
            self.assertEqual(sum(failed["by_category"].values()), failed["total"])
            self.assertEqual(before, [hashlib.sha256(path.read_bytes()).digest() for path in (runs, index)])
        self.assertEqual(measure.classify("unmatched error"), ("orbit_defect", "machine"))
        self.assertEqual(measure.classify("nothing to commit; provider exited"),
                         ("no_change_to_ship", "nothing_to_change"))
        for message in ("", "\n"):
            self.assertEqual(measure.classify(message), ("orbit_defect", "machine"))


if __name__ == "__main__":
    unittest.main()
