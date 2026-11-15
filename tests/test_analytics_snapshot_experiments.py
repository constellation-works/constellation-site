"""Concluded experiment omission guards for analytics snapshots."""

import json
import unittest

from analytics_snapshot_support import (
    HOSTS,
    minimal_docs,
    snapshot,
)


def experiment_pair(ident, name, status="concluded"):
    definition = {
        "id": ident, "name": name, "status": status, "mode": "live",
        "hypothesis": "clean hypothesis", "primary_metric": "delivery_done", "concluded_arm": "treatment",
        "min_sample": 10, "max_days": 14, "segment": 1, "population": {"complexity": ["low"]},
        "guardrails": {}, "updated_at": "2026-11-01T00:00:00Z",
    }
    readout = {
        "as_of": "2026-11-08T00:00:00Z",
        "experiment": {"status": "concluded", "started_at": "2026-10-01T00:00:00Z"},
        "enrollment": {"analysed": 20, "unreadable": 0},
        "arms": [{"name": "treatment", "control": False, "weight": 1, "n": 10,
                  "segments": [{"segment": 1, "n": 10}], "crew_mix": [{"crew": "opus", "tasks": 8}]}],
        "metrics": [],
        "verdict": {"state": "adopt", "arm": "treatment", "label": "adopt", "horizon_reached": True, "reasons": []},
        "warnings": [],
    }
    return definition, readout


class ExperimentOmitTest(unittest.TestCase):
    def test_omit_list_has_a_one_line_public_reason_per_id(self):
        self.assertEqual(snapshot.EXPERIMENT_OMITS["exp-2b6d910d"],
                         "void: treatment not reliably applied and the explorer was removed mid-run")
        for ident, reason in snapshot.EXPERIMENT_OMITS.items():
            with self.subTest(ident=ident):
                self.assertIsNotNone(snapshot.SAFE_ID.fullmatch(ident))
                self.assertTrue(reason.strip())
                self.assertNotIn("\n", reason)

    def test_omitted_experiments_are_counted_and_never_projected(self):
        for ident, name in (
            ("exp-2b6d910d", "hard-tier-explore-first"),
            ("exp-00c7ef1f", "opus-hard-effort-check"),
        ):
            with self.subTest(ident=ident):
                patterns = snapshot.forbidden_patterns(HOSTS)
                dropped = snapshot.empty_dropped()
                redactions = [0]
                omitted_definition, omitted_readout = experiment_pair(ident, name)
                running_definition, _ = experiment_pair("exp-run", "still running", status="running")
                kept_definition, kept_readout = experiment_pair("exp-alpha", "kept")
                pairs = [
                    (omitted_definition, omitted_readout),
                    (omitted_definition, None),  # collect() skips the readout of an omitted id
                    (running_definition, None),
                    (kept_definition, kept_readout),
                ]
                projected = snapshot.project_experiments(pairs, dropped, patterns, redactions)
                self.assertEqual([item["id"] for item in projected], ["exp-alpha"])
                self.assertEqual(dropped["experiments_omitted"], 3)
                self.assertNotIn(ident, json.dumps(projected))
                self.assertNotIn(name, json.dumps(projected))

    def test_guard_refuses_an_omitted_experiment_in_the_public_snapshot(self):
        for ident in snapshot.EXPERIMENT_OMITS:
            with self.subTest(ident=ident):
                docs = minimal_docs()
                snapshot.guard(docs, HOSTS)
                docs["experiments"]["experiments"].append(
                    {"id": ident, "status": "concluded", "hypothesis": "clean hypothesis"})
                with self.assertRaises(SystemExit):
                    snapshot.guard(docs, HOSTS)


if __name__ == "__main__":
    unittest.main()
