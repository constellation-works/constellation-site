"""The public agent-scorecards page rendered from a snapshot."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("site_build", ROOT / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def window(since, until, key="30d"):
    return {"key": key, "since": since, "until": until}


def board(unit, rows, since="2026-10-01T00:00:00Z", until="2026-10-31T00:00:00Z", **extra):
    payload = {
        "min_support": 10,
        "role": "implementers",
        "rows": rows,
        "score_key": f"Score: per 100 {unit}, credit for landed; debits for rework. The fleet average is 100.0.",
        "unit": unit,
        "window": window(since, until),
    }
    payload.update(extra)
    return payload


def row(crew, model, units, rank, score):
    return {
        "below_support": units < 10,
        "crew": crew,
        "model": model,
        "rank": rank,
        "score": score,
        "units": units,
    }


def scorecards():
    return {
        "implementers": board(
            "implemented tasks",
            [
                row("haiku", "claude-haiku-5-5", 30, 1, 146.38),
                row("tiny", "gpt-tiny", 9, 1, 200),
                row("crew unavailable", "claude-haiku-5-5", 40, 2, 10),
                row("legacy", "model unknown", 40, 3, 10),
                row("crew unknown", "gpt-6-luna", 40, 4, 10),
            ],
        ),
        "implementers_by_tier": {
            "cells": [
                {"below_support": True, "crew": "haiku", "crew_mean": 110, "model": "claude-haiku-5-5",
                 "n": 6, "rank": None, "tier": "low", "type": "docs", "units": 6},
                {"below_support": True, "crew": "haiku", "crew_mean": 110, "model": "claude-haiku-5-5",
                 "n": 6, "rank": None, "tier": "low", "type": "ui", "units": 6},
                {"below_support": False, "crew": "opus", "crew_mean": 140, "model": "claude-opus-5-5",
                 "n": 10, "rank": 1, "tier": "low", "type": "ui", "units": 10},
                {"below_support": True, "crew": "thin", "crew_mean": 180, "model": "gpt-thin",
                 "n": 3, "rank": None, "tier": "low", "type": "ui", "units": 3},
                {"below_support": False, "crew": "gap", "crew_mean": 999, "model": "model unknown",
                 "n": 50, "rank": 1, "tier": "low", "type": "ui", "units": 50},
            ],
            "min_support": 10,
            "unit": "tasks",
            "window": window("2026-10-09T09:11:25Z", "2026-11-08T09:11:25Z"),
        },
        "pilots": board(
            "assessed tasks",
            [row("haiku", "claude-haiku-5-5", 20, 1, 47.94)],
            since="2026-10-09T09:11:48Z",
            until="2026-11-08T09:11:48Z",
        ),
        "reviewers": {
            "provisional": board(
                "settled reviews",
                [row("opus", "claude-opus-5-5", 18, 1, 231.74)],
                since="2026-10-09T09:11:36Z",
                until="2026-11-08T09:11:36Z",
                provisional_units=1387,
            ),
            "settled": board(
                "settled reviews",
                [row("luna", "gpt-6-luna", 214, 1, 71.56)],
                since="2026-09-09T09:11:48Z",
                until="2026-10-09T09:11:48Z",
            ),
        },
        "orchestrators": board("attempts", [row("orchestrator-only", "secret-model", 99, 1, 1)]),
    }


def section(doc, element_id):
    marker = f'id="{element_id}"'
    start = doc.index(marker)
    nxt = doc.find('<section class="board"', start + len(marker))
    return doc[start:] if nxt < 0 else doc[start:nxt]


class AgentsPageTest(unittest.TestCase):
    def test_live_snapshot_boards(self):
        directory = build.latest_analytics_dir()
        self.assertIsNotNone(directory)
        data = json.loads((directory / "scorecards.json").read_text(encoding="utf-8"))
        doc = build.render_agents_page(data, directory.name)
        self.assertIn(f"Snapshot {directory.name}.", doc)
        self.assertIn('href="/notes/crew-rankings-method/"', doc)
        for element_id, payload in (
            ("implementers", data["implementers"]),
            ("reviewers", data["reviewers"]["provisional"]),
            ("reviewers-settled", data["reviewers"]["settled"]),
            ("pilots", data["pilots"]),
            ("implementers-low", data["implementers_by_tier"]),
        ):
            block = section(doc, element_id)
            since, until = payload["window"]["since"], payload["window"]["until"]
            self.assertIn(since, block)
            self.assertIn(until, block)
            self.assertIn("UTC.", block)
            self.assertIn("per 100 ", block)
        self.assertIn(">Provisional<", doc)
        self.assertIn(">Settled<", doc)
        self.assertIn(">unranked<", doc)
        self.assertNotIn("orchestrator", doc.lower())
        for gap in ("model unknown", "crew unknown", "crew unavailable"):
            self.assertNotIn(gap, doc)
        for needle in ("ORB-", "jrun-", "/home/", "ws_"):
            self.assertNotIn(needle, doc)
        self.assertNotIn("dropped", doc)

    def test_filters_gaps_unranked_rows_and_orchestrators(self):
        doc = build.render_agents_body(scorecards(), "2026-11-08")
        implementers = section(doc, "implementers")
        self.assertIn("haiku", implementers)
        self.assertIn("per 100 implemented tasks", implementers)
        self.assertIn('data-rank="1"', implementers)
        self.assertIn("tiny", implementers)
        self.assertIn('data-rank="unranked"', implementers)
        for gap in ("crew unavailable", "model unknown", "crew unknown", "orchestrator-only", "secret-model"):
            self.assertNotIn(gap, doc)
        self.assertIn("1,387 reviews in this window are still provisional.", doc)
        self.assertIn(">Provisional<", section(doc, "reviewers"))
        settled = section(doc, "reviewers-settled")
        self.assertIn(">Settled<", settled)
        self.assertIn("2026-09-09T09:11:48Z", settled)
        self.assertIn("per 100 settled reviews", settled)
        self.assertIn("per 100 assessed tasks", section(doc, "pilots"))

    def test_tier_board_sums_types_and_reranks(self):
        low = section(build.render_agents_body(scorecards(), "2026-11-08"), "implementers-low")
        self.assertIn("2026-10-09T09:11:25Z", low)
        self.assertIn("per 100 tasks", low)
        self.assertIn("100 is the fleet average.", low)
        opus = low.index(">opus<")
        haiku = low.index(">haiku<")
        thin = low.index(">thin<")
        self.assertLess(opus, haiku)
        self.assertLess(haiku, thin)

        def ranked(crew_at):
            start = low.rindex("<tr", 0, crew_at)
            return low[start:low.index("</tr>", crew_at)]

        self.assertIn('data-rank="1"', ranked(opus))
        self.assertIn('data-rank="2"', ranked(haiku))
        self.assertIn('data-rank="unranked"', ranked(thin))
        self.assertIn(">12<", ranked(haiku))
        self.assertNotIn("gap", low)

    def test_settled_board_hidden_when_absent(self):
        data = scorecards()
        data["reviewers"]["settled"] = None
        doc = build.render_agents_body(data, "2026-11-08")
        self.assertNotIn("reviewers-settled", doc)
        self.assertNotIn(">Settled<", doc)
        self.assertNotIn("2026-09-09T09:11:48Z", doc)
        self.assertIn(">Provisional<", doc)

    def test_refuses_a_window_other_than_30d(self):
        data = scorecards()
        data["pilots"]["window"]["key"] = "7d"
        with self.assertRaises(SystemExit):
            build.render_agents_body(data, "2026-11-08")

    def test_newest_snapshot_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            older = root / "data" / "analytics" / "2026-01-01"
            newer = root / "data" / "analytics" / "2026-11-08"
            older.mkdir(parents=True)
            newer.mkdir(parents=True)
            (older / "scorecards.json").write_text("{}", encoding="utf-8")
            (newer / "scorecards.json").write_text("{}", encoding="utf-8")
            self.assertEqual(build.latest_analytics_dir(root), newer)
            broken = root / "data" / "analytics" / "2026-12-01"
            broken.mkdir()
            with self.assertRaises(SystemExit):
                build.latest_analytics_dir(root)

    def test_notes_header_stays_current_only_on_notes(self):
        self.assertEqual(build.header_html("notes"), build.HEADER)
        self.assertNotIn('aria-current="page"', build.header_html("analytics"))

    def test_build_writes_the_page_from_the_newest_snapshot(self):
        env = os.environ.copy()
        env["UV_CACHE_DIR"] = str(ROOT / ".orbit" / "tmp" / "uv-cache")
        proc = subprocess.run(
            ["uv", "run", "--with", "markdown==3.8.2", "python3", "build.py"],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        directory = build.latest_analytics_dir()
        self.assertIn(f"from {directory.name}", proc.stdout)
        page = (ROOT / "public" / "analytics" / "agents" / "index.html").read_text(encoding="utf-8")
        self.assertIn(f"Snapshot {directory.name}.", page)
        self.assertIn("Implementers", page)
        self.assertIn("Reviewers", page)
        self.assertIn("Pilots", page)
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", "public/analytics/agents/index.html"],
            cwd=ROOT,
        )
        self.assertEqual(ignored.returncode, 0)


if __name__ == "__main__":
    unittest.main()
