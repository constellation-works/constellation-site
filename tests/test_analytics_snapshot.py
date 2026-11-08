"""Regression coverage for analytics snapshot path redaction (ORB-23163)."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("analytics_snapshot", ROOT / "scripts/analytics_snapshot.py")
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)

HOSTS = ["dk-server-1", "dk-server-2"]
PATH_SAMPLES = [
    "</srv/acme/customer>",
    "</srv/acme/customer.txt>",
    "</my_el/customer.txt>",
    "</my.el/customer>",
    "</home/private/customer.txt>",
    "<~/secret/notes.txt>",
    "<code>/srv/acme/customer</code>",
    "/srv/acme/customer.txt",
    "/root/acme/customer.txt",
    "/mnt/acme/customer.txt",
    "/data/acme/customer.txt",
    "/home/private/customer.txt",
    "/home/daniel/note.txt",
    r"C:\acme\customer.txt",
    "C:/acme/customer.txt",
    r"\\server\share\customer.txt",
    "crates/core/customer.rs",
    "scripts/analytics_snapshot.py",
    "./src/lib.rs",
    "../outside/secret.txt",
    "~/private/customer.txt",
    "/workspace",
    "/srv",
    "/Makefile",
    "file:///etc/passwd",
    "file:///home/daniel/secret/x.txt",
    "FILE:///Users/dan/x",
]
RELATIVE_LEFT = ["src/Makefile"]
API_SOURCES = [
    "GET /api/diagnostics/implement_one?since=30d&outcome=succeeded",
    "GET /api/diagnostics/completions?since=30d",
    "GET /api/metrics/reliability?window=30d",
    "GET /api/tasks/completion-by-complexity",
]


def minimal_docs(hypothesis="clean hypothesis"):
    return {
        "scorecards": {
            "roles": list(snapshot.ROLES),
            "reviewers": {"provisional": {"provisional": True}, "settled": None},
        },
        "metrics": {"source": API_SOURCES[0], "tokens": {"source": API_SOURCES[1]}},
        "reliability": {"source": API_SOURCES[2]},
        "experiments": {
            "source": "orbit experiment list --json; orbit experiment readout --json <id>",
            "experiments": [{"status": "concluded", "hypothesis": hypothesis, "enrollment": {"analysed": 20}}],
        },
        "meta": {"reviewer_settled": False},
    }


def concluded_experiment(text):
    dropped = snapshot.empty_dropped()
    patterns = snapshot.forbidden_patterns(HOSTS)
    redactions = [0]
    readout = {
        "as_of": "2026-11-08T00:00:00Z",
        "experiment": {"status": "concluded", "started_at": "2026-10-01T00:00:00Z"},
        "enrollment": {"analysed": 20, "unreadable": 0},
        "arms": [{"name": "treatment", "control": False, "weight": 1, "n": 10,
                  "segments": [{"segment": 1, "n": 10}], "crew_mix": [{"crew": "opus", "tasks": 8}]}],
        "metrics": [],
        "verdict": {"state": "adopt", "arm": "treatment", "label": text,
                    "horizon_reached": True, "reasons": [text]},
        "warnings": [],
    }
    definition = {
        "id": "exp-alpha", "name": text, "status": "concluded", "mode": "live",
        "hypothesis": text, "primary_metric": "delivery_done", "concluded_arm": "treatment",
        "min_sample": 10, "max_days": 14, "segment": 1,
        "population": {"complexity": ["low"]}, "guardrails": {},
        "updated_at": "2026-11-01T00:00:00Z",
    }
    return snapshot.project_experiment(definition, readout, dropped, patterns, redactions)


class PathRedactionTest(unittest.TestCase):
    def test_sanitize_redacts_paths_outside_old_root_list(self):
        patterns = snapshot.forbidden_patterns(HOSTS)
        for leaked in PATH_SAMPLES:
            with self.subTest(leaked=leaked):
                redactions = [0]
                cleaned = snapshot.sanitize(f"check {leaked} end", patterns, redactions)
                self.assertNotIn(leaked, cleaned)
                self.assertIn("[redacted]", cleaned)
                self.assertGreaterEqual(redactions[0], 1)

    def test_sanitize_preserves_api_sources_and_ordinary_slashes(self):
        patterns = snapshot.forbidden_patterns(HOSTS)
        for source in API_SOURCES:
            self.assertEqual(snapshot.sanitize(source, patterns, [0]), source)
        for prose in ["delivered on 3/4 runs (haiku/luna)", "and/or", "crew / model", "haiku / claude-opus-5-5",
                      "<b>ok</b> <span>done</span>", "</my_el>", "</my.el>", "<my_el>ok</my_el> <my.el>ok</my.el>"]:
            with self.subTest(prose=prose):
                self.assertEqual(snapshot.sanitize(prose, patterns, [0]), prose)

    def test_guard_accepts_closing_tags_with_underscore_or_dot_names(self):
        snapshot.guard(minimal_docs("see </my_el> and </my.el> in prose"), HOSTS)

    def test_sanitize_leaves_relative_paths_without_extension(self):
        patterns = snapshot.forbidden_patterns(HOSTS)
        for relative in RELATIVE_LEFT:
            with self.subTest(relative=relative):
                self.assertEqual(snapshot.sanitize(f"check {relative} end", patterns, [0]),
                                 f"check {relative} end")

    def test_projection_redacts_free_text_and_preserves_aggregates(self):
        for leaked in PATH_SAMPLES:
            with self.subTest(leaked=leaked):
                experiment = concluded_experiment(f"Investigate {leaked} now")
                blob = json.dumps(experiment)
                self.assertNotIn(leaked, blob)
                self.assertIn("[redacted]", blob)
                self.assertEqual(experiment["enrollment"], {"analysed": 20, "unreadable": 0})
                self.assertEqual(experiment["arms"][0]["n"], 10)
                self.assertEqual(experiment["arms"][0]["crew_mix"], [{"crew": "opus", "tasks": 8}])

    def test_guard_rejects_paths_and_accepts_api_sources(self):
        snapshot.guard(minimal_docs(), HOSTS)
        for leaked in PATH_SAMPLES:
            with self.subTest(leaked=leaked):
                with self.assertRaises(SystemExit):
                    snapshot.guard(minimal_docs(f"Investigate {leaked}"), HOSTS)

    def test_replay_rejects_tampered_bundle_and_preserves_clean_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle.json"
            bundle.write_text(snapshot.dump(minimal_docs()))
            out = root / "out"
            snapshot.replay(str(bundle), str(out))
            for source in API_SOURCES[:1]:
                self.assertIn(source, (out / "metrics.json").read_text())
            self.assertIn(API_SOURCES[2], (out / "reliability.json").read_text())
            bundle.write_text(snapshot.dump(minimal_docs("see crates/core/customer.rs")))
            bad_out = root / "bad-out"
            with self.assertRaises(SystemExit):
                snapshot.replay(str(bundle), str(bad_out))
            self.assertFalse((bad_out / "experiments.json").exists())


if __name__ == "__main__":
    unittest.main()
