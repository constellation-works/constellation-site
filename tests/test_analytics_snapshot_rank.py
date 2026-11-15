"""Settled model-rank projection and replay checks."""

import json
from pathlib import Path
import tempfile
import unittest

from analytics_snapshot_support import (
    HOSTS,
    minimal_docs,
    snapshot,
)


def rank_payload(**overrides):
    payload = {
        "window": "30d", "since": "2026-10-10T07:34:21Z", "until": "2026-11-09T07:34:21Z",
        "settle_lag": "14d", "execution": "managed", "live": False, "provisional": False, "status": "ok",
        "qualified": True, "scales_source": "season",
        "measures": [{"key": "escaped_regressions", "label": "Escaped regressions", "weight": 30.0, "sign": -1.0,
                      "pillar": "quality", "status": "measured", "units": "implemented tasks",
                      "definition": "Escaped regressions, see /home/daniel/rank.rs", "reason": None}],
        "weights_total": 30.0,
        "rules": {"shrinkage_k": 30.0, "min_tasks": 30, "min_tiers": 2, "min_tier_tasks": 5, "min_eligible_models": 3},
        "unattributed": {"tasks": 3, "crews": [{"crew": "secret-crew", "tasks": 3}]},
        "paired_probabilities": {"gpt-a": {"gpt-b": 0.9}},
        "rows": [
            {"model": "gpt-a", "rank": 1, "rank_label": "1", "band_size": 1, "eligible": True, "units": 40,
             "tasks_by_tier": {"low": 20, "medium": 20}, "score": 110.0, "raw_score": 112.0,
             "interval": {"p10": 105.0, "p90": 115.0}, "z": 1.0,
             "cost": {"ratio": 0.8, "per_task": 1.0, "expected_per_task": 1.25, "coverage": 0.9, "cost_unknown": False},
             "measures": {"escaped_regressions": {"status": "measured", "weight": 30.0, "units": 40,
                                                  "unit": "implemented tasks", "actual": 1.0, "expected": 2.0,
                                                  "residual": 0.1, "contribution": 3.0}},
             "landed_tasks": 39.0, "landed_rate": 0.975,
             "crews": [{"crew": "sol", "tasks": 38}, {"crew": "crew unknown", "tasks": 2}],
             "effort_split": [{"crew": None, "model": "gpt-a", "provider_cost_usd": 1.0}],
             "tiers": [{"tier": "low", "tasks": 20, "score": 108.0, "cost_per_task": 0.5,
                        "cost_coverage": 1.0, "cost_unknown": False}]},
            {"model": "model unknown", "rank": None, "eligible": False, "units": 9},
            {"model": "gpt-thin", "rank": None, "eligible": False, "ineligible_reason": "8 implemented tasks; 30 needed",
             "units": 8, "tasks_by_tier": {"hard": 8}, "score": 120.0, "interval": None},
        ],
    }
    payload.update(overrides)
    return payload


class RankProjectionTest(unittest.TestCase):
    def project(self, payload):
        dropped = snapshot.empty_dropped()
        projected = snapshot.project_rank(payload, dropped, snapshot.forbidden_patterns(HOSTS), [0])
        return projected, dropped

    def test_projection_keeps_public_fields_and_drops_gaps(self):
        rank, dropped = self.project(rank_payload())
        self.assertEqual([row["model"] for row in rank["rows"]], ["gpt-a", "gpt-thin"])
        self.assertEqual(rank["rows"][0]["crews"], [{"crew": "sol", "tasks": 38}])
        self.assertEqual(dropped["rank"], 2)
        self.assertEqual(rank["source"], snapshot.RANK_SOURCE)
        # The settled board: no live query, with the settled window and settle lag.
        self.assertNotIn("live=", rank["source"])
        source = Path(snapshot.__file__).read_text(encoding="utf-8")
        # Keep the source guard over the implementation after its module split.
        source += "\n".join(path.read_text(encoding="utf-8") for path in
                            Path(snapshot.__file__).with_name("_analytics_snapshot").glob("*.py"))
        self.assertNotIn("live=true", source)
        self.assertNotIn('"live": "true"', source)
        self.assertEqual(rank["window"], {"key": "30d", "since": "2026-10-10T07:34:21Z", "until": "2026-11-09T07:34:21Z"})
        self.assertIs(rank["live"], False)
        self.assertIs(rank["provisional"], False)
        self.assertEqual(rank["settle_lag"], "14d")
        self.assertEqual(rank["scales_source"], "season")
        self.assertIs(rank["qualified"], True)
        self.assertEqual(rank["execution"], "managed")
        self.assertEqual(rank["rows"][1]["ineligible_reason"], "8 implemented tasks; 30 needed")
        self.assertIsNone(rank["rows"][0]["ineligible_reason"])
        self.assertEqual(rank["eligibility_rule"], "At least 30 implemented tasks spanning at least 2 assessed tiers "
                                                   "with at least 5 tasks each. The board needs 3 such models.")
        blob = json.dumps(rank)
        for private in ("paired_probabilities", "effort_split", '"z"', "secret-crew", "/home/daniel"):
            self.assertNotIn(private, blob)

    def test_eligibility_rule_follows_orbits_rule(self):
        # ORB-23672 moves Orbit to one assessed tier; the sentence follows the numbers.
        rules = {"shrinkage_k": 30.0, "min_tasks": 30, "min_tiers": 1, "min_tier_tasks": 5}
        rank, _ = self.project(rank_payload(rules=rules))
        self.assertEqual(rank["eligibility_rule"], "At least 30 implemented tasks, with at least 5 in one assessed tier.")
        # Orbit's own sentence wins, sanitized.
        rank, _ = self.project(rank_payload(eligibility_rule="30 tasks; one tier of 5+, see /home/daniel/rank.rs"))
        self.assertTrue(rank["eligibility_rule"].startswith("30 tasks; one tier of 5+"))
        self.assertNotIn("/home/daniel", rank["eligibility_rule"])
        rank, _ = self.project(rank_payload(rules={}))
        self.assertIsNone(rank["eligibility_rule"])

    def test_single_tier_flag_is_kept_only_as_a_tier_or_true(self):
        for value, expected in (("hard", "hard"), (True, True), ({"tier": "low"}, "low"), ("<b>", None), (1, None)):
            with self.subTest(value=value):
                payload = rank_payload()
                payload["rows"][0]["single_tier"] = value
                rank, _ = self.project(payload)
                self.assertEqual(rank["rows"][0].get("single_tier"), expected)

    def test_projection_refuses_live_unmanaged_or_other_windows(self):
        for overrides in ({"live": True}, {"provisional": True}, {"live": True, "provisional": True},
                          {"execution": "all"}, {"window": "7d"}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(SystemExit):
                    self.project(rank_payload(**overrides))

    def test_replay_writes_rank_only_when_the_bundle_has_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle.json"
            docs = minimal_docs()
            bundle.write_text(snapshot.dump(docs))
            snapshot.replay(str(bundle), str(root / "without"))
            self.assertFalse((root / "without" / "rank.json").exists())
            self.assertTrue((root / "without" / "scorecards.json").exists())
            docs["rank"], _ = self.project(rank_payload())
            bundle.write_text(snapshot.dump(docs))
            snapshot.replay(str(bundle), str(root / "with"))
            written = json.loads((root / "with" / "rank.json").read_text())
            self.assertEqual(written["rows"][0]["model"], "gpt-a")
            self.assertIs(written["live"], False)
            self.assertEqual(written["settle_lag"], "14d")
            self.assertEqual(written["window"]["until"], "2026-11-09T07:34:21Z")
            # A bundle published while the live board was current still replays.
            docs["rank"]["live"] = docs["rank"]["provisional"] = True
            bundle.write_text(snapshot.dump(docs))
            snapshot.replay(str(bundle), str(root / "live"))
            self.assertIs(json.loads((root / "live" / "rank.json").read_text())["live"], True)
            # Live without provisional (or the reverse) is refused.
            docs["rank"]["provisional"] = False
            bundle.write_text(snapshot.dump(docs))
            with self.assertRaises(SystemExit):
                snapshot.replay(str(bundle), str(root / "mixed"))

    def test_system_is_dropped_from_rank_crews_and_counted_with_gaps(self):
        payload = rank_payload()
        payload["rows"][0]["crews"] = [
            {"crew": "sol", "tasks": 800},
            {"crew": "sol@high", "tasks": 10},
            {"crew": "sol@xhigh", "tasks": 4},
            {"crew": "system", "tasks": 2},
            {"crew": "crew unknown", "tasks": 1},
        ]
        rank, dropped = self.project(payload)
        row = rank["rows"][0]
        self.assertEqual(row["crews"], [
            {"crew": "sol", "tasks": 800},
            {"crew": "sol@high", "tasks": 10},
            {"crew": "sol@xhigh", "tasks": 4},
        ])
        # Model numbers stay Orbit's. system is not folded into them.
        self.assertEqual(row["units"], 40)
        self.assertEqual(row["score"], 110.0)
        self.assertEqual(row["rank"], 1)
        # model unknown + crew unknown + system
        self.assertEqual(dropped["rank"], 3)
        self.assertNotIn('"system"', json.dumps(rank))
        self.assertNotIn("system", snapshot.GAP_CREWS)

    def test_bare_rank_crew_carries_no_effort_and_no_estimate(self):
        payload = rank_payload()
        payload["rows"][0]["crews"] = [
            {"crew": "argon", "tasks": 4, "effort_estimate": "high"},
            {"crew": "haiku@xhigh", "tasks": 1},
        ]
        rank, dropped = self.project(payload)
        # A configured effort in the payload is never copied: effort is read from recorded invocations only.
        self.assertEqual(rank["rows"][0]["crews"], [
            {"crew": "argon", "tasks": 4},
            {"crew": "haiku@xhigh", "tasks": 1},
        ])
        self.assertEqual(dropped["rank"], 1)  # the gap model only

    def test_guard_rejects_a_leaked_path_in_rank(self):
        docs = minimal_docs()
        docs["rank"], _ = self.project(rank_payload())
        snapshot.guard(docs, HOSTS)
        docs["rank"]["rows"][1]["ineligible_reason"] = "see /srv/acme/customer.txt"
        with self.assertRaises(SystemExit):
            snapshot.guard(docs, HOSTS)


if __name__ == "__main__":
    unittest.main()
