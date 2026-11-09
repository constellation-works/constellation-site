"""The weekly crew-ranking note: scripts/crew_rankings.py and its build.py support (ORB-23608)."""

import csv
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "crew_rankings.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load("site_build", ROOT / "build.py")
fixtures = load("ranking_fixtures", ROOT / "tests" / "test_analytics_agents.py")


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)


class CrewRankingScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.frozen = base / "frozen"
        self.frozen.mkdir()
        (self.frozen / "scorecards.json").write_text(json.dumps(fixtures.effort_scorecards()), encoding="utf-8")
        self.notes, self.data = base / "notes", base / "data"
        self.args = ["2026-11-09", "--from", str(self.frozen), "--notes-dir", str(self.notes), "--data-dir", str(self.data)]

    def generate(self, *extra):
        proc = run(*self.args, *extra)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return self.notes / "crew-rankings-2026-11-09"

    def test_writer_only_returns_the_rank_1_all_tiers_crew_and_writes_nothing(self):
        proc = run(*self.args, "--writer-only")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        writer = json.loads(proc.stdout)
        self.assertEqual((writer["crew"], writer["source"], writer["model"], writer["score"]),
                         ("sol", "mvp", "gpt-6.1-sol", 132.6))
        self.assertEqual((writer["effort"], writer["effort_estimate"]), ("unknown", "high"))
        self.assertFalse(self.notes.exists() or self.data.exists())
        self.assertEqual(json.loads(run(*self.args, "--writer-only", "--crews", "opus").stdout)["crew"], "opus")

    def test_note_title_byline_and_body_order(self):
        note = self.generate()
        text = (note / "index.md").read_text(encoding="utf-8")
        meta = dict(re.findall(r"^(\w+): (.*)$", text.split("---")[1], re.M))
        self.assertEqual(meta["title"], "[Crew Ranking - 2026-11-09]: MVP sol")
        # The MVP is named with the boards' own crew@effort label; the title keeps the plain crew.
        self.assertEqual(meta["author"], "sol@high (est.) (gpt-6.1-sol), MVP of the week, 132.6")
        self.assertIn("MVP: sol@high (est.), gpt-6.1-sol, 132.6.", meta["summary"])
        self.assertEqual(meta["status"], "draft")
        body = text.split("---", 2)[2]
        order = [body.index(marker) for marker in (
            "](../crew-rankings-method/)", "**MVP: sol@high (est.), gpt-6.1-sol, 132.6**",
            "## Victory address", "{{victory-address}}", "## Crews by role",
            f"<!-- crews-by-role: {self.data / '2026-11-09'} -->", "Limits:")]
        self.assertEqual(order, sorted(order))
        for gone in ("crown", "Crown", "pooled", "shrink", "K = "):
            self.assertNotIn(gone, text)
        self.assertEqual(sorted(p.name for p in note.iterdir()),
                         ["all-tiers.csv", "by-tier.csv", "index.md", "pilots.csv", "reviewers.csv"])
        with open(note / "all-tiers.csv", newline="") as f:
            first = next(csv.DictReader(f))
        self.assertEqual((first["rank"], first["crew"], first["effort"], first["score"]), ("1", "sol", "unknown", "132.6"))
        # The frozen input is the renderer's scorecards.json, and the facts name the MVP.
        frozen = self.data / "2026-11-09"
        self.assertEqual(json.loads((frozen / "scorecards.json").read_text()), fixtures.effort_scorecards())
        mvp = json.loads((frozen / "facts.json").read_text())["mvp"]
        self.assertEqual((mvp["crew"], mvp["label"]), ("sol", "sol@high (est.)"))

    def test_a_recorded_mvp_effort_drops_the_estimate_mark(self):
        cards = fixtures.effort_scorecards()
        top = cards["implementers"]["rows"][0]
        top["reasoning_effort"], top["effort_label"] = "medium", "medium"
        top.pop("effort_estimate", None)
        (self.frozen / "scorecards.json").write_text(json.dumps(cards), encoding="utf-8")
        text = (self.generate() / "index.md").read_text(encoding="utf-8")
        self.assertIn("author: sol@medium (gpt-6.1-sol), MVP of the week, 132.6", text)
        self.assertIn("**MVP: sol@medium, gpt-6.1-sol, 132.6**", text)
        self.assertNotIn("(est.)", text.split("## Crews by role")[0])
        self.assertIn("title: [Crew Ranking - 2026-11-09]: MVP sol\n", text)

    def test_an_existing_note_is_not_overwritten_without_force(self):
        note = self.generate()
        (note / "index.md").write_text("written address", encoding="utf-8")
        proc = run(*self.args)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual((note / "index.md").read_text(encoding="utf-8"), "written address")
        self.generate("--force")

    def test_script_has_no_crown_method_left(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for gone in ("crown", "pool_models", "shrink", "K_SENSITIVITY", "CROWN_K"):
            self.assertNotIn(gone, source)
        self.assertIn('"--until"', source)


NOTE = """---
title: [Crew Ranking - 2026-11-09]: MVP sol
summary: The crew boards.
status: {status}
date: 2026-11-09
author: sol@high (est.) (gpt-6.1-sol), MVP of the week, 132.6
tags: rankings, weekly
---

{address}
"""


class CrewRankingBuild(unittest.TestCase):
    def note(self, status, address):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "crew-rankings-2026-11-09" / "index.md"
        path.parent.mkdir()
        path.write_text(NOTE.format(status=status, address=address), encoding="utf-8")
        return path

    def test_published_note_with_the_placeholder_fails_and_a_draft_builds(self):
        with self.assertRaises(SystemExit) as caught:
            build.parse(self.note("published", "{{victory-address}} sol writes here."))
        self.assertIn("victory address", str(caught.exception))
        draft = build.parse(self.note("draft", "{{victory-address}} sol writes here."))
        self.assertEqual(draft["status"], "draft")
        published = build.parse(self.note("published", "I landed the most."))
        self.assertEqual(published["authors"], ["sol@high (est.) (gpt-6.1-sol), MVP of the week, 132.6"])

    def test_plain_comma_separated_authors_still_split(self):
        path = self.note("draft", "Text.")
        path.write_text(path.read_text().replace(
            "author: sol@high (est.) (gpt-6.1-sol), MVP of the week, 132.6", "author: Ann, Bo"))
        self.assertEqual(build.parse(path)["authors"], ["Ann", "Bo"])

    def test_embed_is_the_ranking_pages_stacked_crews_by_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "data" / "crew-rankings" / "2026-11-09"
            directory.mkdir(parents=True)
            (directory / "scorecards.json").write_text(json.dumps(fixtures.effort_scorecards()), encoding="utf-8")
            with mock.patch.object(build, "ROOT", Path(tmp)):
                body = build.render_body("Intro.\n\n<!-- crews-by-role: data/crew-rankings/2026-11-09 -->\n\nLimits.\n")
                html, embedded = build.embed_crews_by_role(body, "note")
                self.assertTrue(embedded)
                self.assertIn('<div class="analytics crews-embed">\n' + build.render_crews_by_role(directory) + "\n</div>", html)
                self.assertNotIn("<!-- crews-by-role", html)
                self.assertEqual(build.embed_crews_by_role("<p>plain</p>", "note"), ("<p>plain</p>", False))
                for bad in ("data/analytics/2026-11-09", "data/crew-rankings/2026-11-10", "../x"):
                    with self.assertRaises(SystemExit):
                        build.embed_crews_by_role(f"<!-- crews-by-role: {bad} -->", "note")


if __name__ == "__main__":
    unittest.main()
