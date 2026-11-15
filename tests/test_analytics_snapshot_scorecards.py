"""Recorded-effort identity in analytics snapshot scorecards."""

from pathlib import Path
import tempfile
import unittest

from analytics_snapshot_support import (
    HOSTS,
    minimal_docs,
    snapshot,
)


def scorecard_row(crew, model, effort, label, units=12, rank=1, score=110.0):
    row = {"crew": crew, "model": model, "units": units, "rank": rank, "score": score,
           "below_support": False, "unjudged": False, "label": f"{model} @ {label}"}
    if effort is not ...:
        row["reasoning_effort"] = effort
    if label is not None:
        row["effort_label"] = label
    return row


class EffortIdentityTest(unittest.TestCase):
    """Scorecard rows are one model at one recorded effort (ORB-23657)."""

    def card(self, rows):
        return {"role": "implementers", "window": "30d", "since": "2026-10-10T00:00:00Z",
                "until": "2026-11-09T00:00:00Z", "min_support": 10, "unit": "tasks",
                "fleet_average": 100, "terms": [], "rows": rows}

    def test_rows_copy_reasoning_effort_and_effort_label(self):
        dropped = snapshot.empty_dropped()
        board = snapshot.project_board(self.card([
            scorecard_row("sol", "gpt-6.1-sol", "unknown", "effort unknown", score=132.6),
            scorecard_row("sol", "gpt-6.1-sol", "high", "high", rank=2, score=115.5),
            scorecard_row("argon", "gemini-4-argon-high", None, "provider default", rank=3, score=90.0),
            scorecard_row("bad", "gpt-bad", "<script>", "evil\nlabel", rank=4, score=80.0),
            scorecard_row("legacy", "gpt-legacy", ..., None, rank=5, score=70.0),
        ]), False, dropped, "implementers")
        rows = {(row["crew"], row.get("reasoning_effort")): row for row in board["rows"]}
        self.assertEqual(rows[("sol", "unknown")]["effort_label"], "effort unknown")
        self.assertEqual(rows[("sol", "high")]["effort_label"], "high")
        # No recorded effort: the label is kept, the null effort is not copied.
        self.assertEqual(rows[("argon", None)]["effort_label"], "provider default")
        self.assertNotIn("reasoning_effort", rows[("argon", None)])
        # Values outside the allowlists are dropped, not published.
        self.assertNotIn("effort_label", rows[("bad", None)])
        self.assertNotIn("reasoning_effort", rows[("bad", None)])
        # A row from before the split carries neither field.
        self.assertNotIn("effort_label", rows[("legacy", None)])
        # The composite scorecard label is not copied.
        self.assertTrue(all("label" not in row for row in board["rows"]))

    def test_by_tier_cells_copy_reasoning_effort_and_effort_label(self):
        dropped = snapshot.empty_dropped()
        cells = snapshot.project_cells({
            "min_support": 10, "window": "30d", "since": "2026-10-10T00:00:00Z", "until": "2026-11-09T00:00:00Z",
            "cells": [
                {"tier": "low", "type": "ui", "crew": "sol", "model": "gpt-6.1-sol", "n": 12, "crew_mean": 120,
                 "reasoning_effort": "high", "effort_label": "high", "label": "gpt-6.1-sol @ high"},
                {"tier": "low", "type": "ui", "crew": "sol", "model": "gpt-6.1-sol", "n": 12, "crew_mean": 130,
                 "reasoning_effort": "unknown", "effort_label": "effort unknown"},
                {"tier": "low", "type": "ui", "crew": "old", "model": "gpt-old", "n": 12, "crew_mean": 90},
            ],
        }, dropped)["cells"]
        self.assertEqual(
            [(cell["crew"], cell.get("reasoning_effort"), cell.get("effort_label"), cell["rank"]) for cell in cells],
            [("sol", "unknown", "effort unknown", 1), ("sol", "high", "high", 2), ("old", None, None, 3)],
        )
        self.assertTrue(all("label" not in cell for cell in cells))

    def docs_with(self, rows, board="implementers"):
        docs = minimal_docs()
        dropped = snapshot.empty_dropped()
        projected = snapshot.project_board(self.card(rows), board == "reviewers", dropped, board)
        if board == "reviewers":
            docs["scorecards"]["reviewers"]["provisional"] = projected
        else:
            docs["scorecards"][board] = projected
        return docs

    def test_guard_accepts_one_crew_and_model_at_two_efforts(self):
        snapshot.guard(self.docs_with([
            scorecard_row("sol", "gpt-6.1-sol", "unknown", "effort unknown"),
            scorecard_row("sol", "gpt-6.1-sol", "high", "high", rank=2),
            scorecard_row("argon", "gemini-4-argon-high", None, "provider default", rank=3),
        ]), HOSTS)

    def test_guard_fails_two_rows_with_the_same_crew_model_and_effort(self):
        for board in ("implementers", "reviewers", "pilots"):
            for effort, label in (("high", "high"), (..., None)):
                with self.subTest(board=board, effort=effort):
                    docs = self.docs_with([
                        scorecard_row("sol", "gpt-6.1-sol", effort, label, score=132.6),
                        scorecard_row("sol", "gpt-6.1-sol", effort, label, rank=2, score=115.5),
                    ], board)
                    with self.assertRaises(SystemExit) as raised:
                        snapshot.guard(docs, HOSTS)
                    self.assertIn("two rows for crew sol, model gpt-6.1-sol", str(raised.exception))

    def test_guard_fails_a_replayed_bundle_that_dropped_the_effort(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "bundle.json"
            docs = self.docs_with([
                scorecard_row("sol", "gpt-6.1-sol", "unknown", "effort unknown"),
                scorecard_row("sol", "gpt-6.1-sol", "high", "high", rank=2),
            ])
            for row in docs["scorecards"]["implementers"]["rows"]:
                del row["reasoning_effort"]
                del row["effort_label"]
            bundle.write_text(snapshot.dump(docs))
            with self.assertRaises(SystemExit):
                snapshot.replay(str(bundle), str(Path(directory) / "out"))
            self.assertFalse((Path(directory) / "out" / "scorecards.json").exists())

    def test_new_snapshots_carry_no_effort_estimate(self):
        # A row or cell that arrives with an effort_estimate (an older snapshot) is not copied.
        dropped = snapshot.empty_dropped()
        board = snapshot.project_board(self.card([
            dict(scorecard_row("sol", "gpt-6.1-sol", "unknown", "effort unknown", score=132.6),
                 effort_estimate="high"),
            scorecard_row("sol", "gpt-6.1-sol", "high", "high", rank=2, score=115.5),
            scorecard_row("argon", "gemini-4-argon-high", "unknown", "effort unknown", rank=3, score=90.0),
            scorecard_row("argon", "gemini-4-argon-high", None, "provider default", rank=4, score=80.0),
        ]), False, dropped, "implementers")
        rows = [(row["crew"], row.get("reasoning_effort")) for row in board["rows"]]
        self.assertEqual(rows, [("sol", "unknown"), ("sol", "high"),
                                ("argon", "unknown"), ("argon", None)])
        self.assertTrue(all("effort_estimate" not in row for row in board["rows"]))
        cells = snapshot.project_cells({
            "min_support": 10, "window": "30d",
            "cells": [{"tier": "low", "type": "ui", "crew": "sol", "model": "gpt-6.1-sol", "n": 12,
                       "crew_mean": 120, "reasoning_effort": "unknown", "effort_label": "effort unknown",
                       "effort_estimate": "high"}],
        }, dropped)["cells"]
        self.assertNotIn("effort_estimate", cells[0])
        self.assertEqual(cells[0]["effort_label"], "effort unknown")

    def test_no_crew_configuration_is_read_for_effort(self):
        self.assertFalse(hasattr(snapshot, "crew_effort_estimates"))
        self.assertFalse(hasattr(snapshot, "crews_needing_estimates"))
        self.assertFalse(hasattr(snapshot, "rank_bare_crews"))


if __name__ == "__main__":
    unittest.main()
