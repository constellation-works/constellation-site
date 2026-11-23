"""The weekly crew-ranking note: scripts/crew_rankings.py and its build.py support (ORB-23608, ORB-23847)."""

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
import build_notes
fixtures = load("ranking_fixtures", ROOT / "tests" / "test_analytics_agents.py")
crew_rankings = load("crew_rankings_script", SCRIPT)


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)


def front_matter(text):
    return dict(re.findall(r"^(\w+): (.*)$", text.split("---")[1], re.M))


def model_row(model, rank, label, score, crews, eligible=True):
    """One model row of the settled rank board; each crew carries its own implemented-task count."""
    row = fixtures.rank_row(model, rank, label, score, sum(tasks for _crew, tasks in crews),
                            [crew for crew, _tasks in crews], eligible=eligible)
    row["crews"] = [{"crew": crew, "tasks": tasks} for crew, tasks in crews]
    if not eligible:
        row["rank"], row["rank_label"], row["band_size"], row["interval"] = None, None, None, None
    return row


def rank_board(*rows, scales="season", qualified=True):
    """A settled rank.json: live and provisional false, as the snapshot freezes it, with Orbit's band order."""
    return {
        "role": "implementers", "execution": "managed", "status": "ok",
        "live": False, "provisional": False, "qualified": qualified, "scales_source": scales,
        "settle_lag": "14d", "eligible_models": sum(1 for row in rows if row["eligible"]),
        "window": {"key": "30d", "since": "2026-09-25T00:00:00Z", "until": "2026-10-25T00:00:00Z"},
        "measures": [], "not_scored": {"count": 0, "reasons": {}}, "rules": {"min_tasks": 30},
        "rows": list(rows),
    }


# A shared top band, cheapest first: the first model writes the address through its only crew.
TIED_BAND = [
    model_row("gpt-6.1-sol", 1, "1=", 114.6, [("sol", 825)]),
    model_row("gpt-6-sol", 1, "1=", 119.1, [("sol", 104)]),
    model_row("claude-haiku-5-5", 2, "2=", 103.1, [("haiku@high", 40), ("haiku@xhigh", 200)]),
    model_row("gpt-tiny", None, None, 130.0, [("tiny", 9)], eligible=False),
]
HAIKU_ROW = model_row("claude-haiku-5-5", 1, "1", 103.0, [("haiku@high", 40), ("haiku@xhigh", 200)])
LUNA_ROW = model_row("gpt-6-luna", 2, "2", 99.0, [("luna", 50)])


class CrewRankingScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.frozen = base / "frozen"
        self.frozen.mkdir()
        (self.frozen / "scorecards.json").write_text(json.dumps(fixtures.effort_scorecards()), encoding="utf-8")
        self.freeze(rank_board(*TIED_BAND))
        self.notes, self.data = base / "notes", base / "data"
        self.args = ["2026-11-09", "--from", str(self.frozen), "--notes-dir", str(self.notes), "--data-dir", str(self.data)]

    def freeze(self, board):
        (self.frozen / "rank.json").write_text(json.dumps(board), encoding="utf-8")

    def generate(self, *extra):
        proc = run(*self.args, *extra)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return self.notes / "crew-rankings-2026-11-09"

    def test_writer_only_names_the_band_writer_and_writes_nothing(self):
        proc = run(*self.args, "--writer-only")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        writer = json.loads(proc.stdout)
        self.assertEqual((writer["crew"], writer["source"], writer["model"], writer["score"]),
                         ("sol", "mvp", "gpt-6.1-sol", 114.6))
        self.assertEqual(writer["mvp_crew"], "sol")
        self.assertFalse(self.notes.exists() or self.data.exists())
        self.assertEqual(json.loads(run(*self.args, "--writer-only", "--crews", "opus").stdout),
                         {"crew": "opus", "source": "fallback", "mvp_crew": "sol", "model": "gpt-6.1-sol",
                          "effort": None, "score": 114.6, "units": 825})

    def test_a_writing_crew_named_for_its_effort_routes_to_its_plain_crew(self):
        self.freeze(rank_board(HAIKU_ROW, LUNA_ROW))
        writer = json.loads(run(*self.args, "--writer-only", "--crews", "haiku").stdout)
        self.assertEqual((writer["crew"], writer["source"], writer["mvp_crew"], writer["effort"]),
                         ("haiku", "mvp", "haiku@xhigh", "xhigh"))

    def test_a_shared_top_band_is_published_as_co_mvps_and_the_first_models_crew_writes(self):
        note = self.generate()
        text = (note / "index.md").read_text(encoding="utf-8")
        meta = front_matter(text)
        self.assertEqual(meta["title"], "[Crew Ranking - 2026-11-09]: co-MVPs gpt-6.1-sol and gpt-6-sol")
        self.assertEqual(meta["author"], "sol (gpt-6.1-sol), MVP of the week, 114.6")
        self.assertEqual(meta["status"], "draft")
        self.assertIn("Co-MVPs: gpt-6.1-sol at 114.6 (p10–p90 110.6–118.6); "
                      "gpt-6-sol at 119.1 (p10–p90 115.1–123.1).", meta["summary"])
        body = text.split("---", 2)[2]
        self.assertIn("**Co-MVPs, rank 1=: gpt-6.1-sol at 114.6 (p10–p90 110.6–118.6); "
                      "gpt-6-sol at 119.1 (p10–p90 115.1–123.1).**", body)
        self.assertIn("its first model, gpt-6.1-sol, writes the address, through its crew sol", body)
        self.assertIn("{{victory-address}} sol replaces this line", body)
        self.assertIn("Limits:", body)
        self.assertEqual(sorted(p.name for p in note.iterdir()),
                         ["all-tiers.csv", "by-tier.csv", "index.md", "pilots.csv", "reviewers.csv"])
        with open(note / "all-tiers.csv", newline="") as f:
            first = next(csv.DictReader(f))
        self.assertEqual((first["rank"], first["crew"]), ("1", "sol"))
        frozen = self.data / "2026-11-09"
        self.assertEqual(json.loads((frozen / "scorecards.json").read_text()), fixtures.effort_scorecards())
        self.assertEqual(json.loads((frozen / "rank.json").read_text()), rank_board(*TIED_BAND))
        facts = json.loads((frozen / "facts.json").read_text())
        self.assertEqual([m["model"] for m in facts["mvp"]["models"]], ["gpt-6.1-sol", "gpt-6-sol"])
        self.assertEqual((facts["writer"]["crew"], facts["writer"]["source"]), ("sol", "mvp"))
        self.assertIsNone(facts["reason"])
        build.parse(note / "index.md")  # a draft with its placeholder builds

    def test_a_single_mvp_quotes_score_and_interval_and_its_top_crew_writes(self):
        self.freeze(rank_board(HAIKU_ROW, LUNA_ROW))
        text = (self.generate() / "index.md").read_text(encoding="utf-8")
        meta = front_matter(text)
        self.assertEqual(meta["title"], "[Crew Ranking - 2026-11-09]: MVP claude-haiku-5-5")
        self.assertEqual(meta["author"], "haiku@xhigh (claude-haiku-5-5), MVP of the week, 103.0")
        self.assertIn("MVP: claude-haiku-5-5 at 103.0 (p10–p90 99.0–107.0).", meta["summary"])
        body = text.split("---", 2)[2]
        self.assertIn("**MVP: claude-haiku-5-5, rank 1, 103.0 (p10–p90 99.0–107.0)** on 240 implemented tasks.", body)
        self.assertIn("is the only model in the top band, so its crew haiku@xhigh writes the address", body)
        self.assertIn("{{victory-address}} haiku@xhigh replaces this line", body)

    def test_an_unqualified_or_uncalibrated_board_names_no_mvp_and_the_fallback_writes(self):
        cases = [
            (rank_board(*TIED_BAND, scales="window_estimate"),
             "the noise scales are estimated from this window, not frozen for a calibrated season"),
            (rank_board(*TIED_BAND, qualified=False), "the model board has not qualified"),
        ]
        for board, why in cases:
            with self.subTest(why=why):
                self.freeze(board)
                text = (self.generate("--force") / "index.md").read_text(encoding="utf-8")
                meta = front_matter(text)
                self.assertEqual(meta["title"], "[Crew Ranking - 2026-11-09]: no MVP")
                self.assertEqual(meta["author"], "opus (fallback writer), no MVP this week")
                self.assertIn(f"No MVP: {why}.", meta["summary"])
                body = text.split("---", 2)[2]
                self.assertIn(f"**No MVP this week:** {why}.", body)
                self.assertIn("{{victory-address}} opus replaces this line", body)
                self.assertNotIn("**MVP:", body)
                writer = json.loads(run(*self.args, "--writer-only").stdout)
                self.assertEqual((writer["crew"], writer["source"]), ("opus", "fallback"))
                facts = json.loads((self.data / "2026-11-09" / "facts.json").read_text())
                self.assertIsNone(facts["mvp"])
                self.assertEqual(facts["reason"], why)
                build.parse(self.notes / "crew-rankings-2026-11-09" / "index.md")

    def test_an_mvp_with_no_recorded_crew_hands_the_address_to_the_fallback(self):
        self.freeze(rank_board(model_row("claude-haiku-5-5", 1, "1", 103.0, []), LUNA_ROW))
        text = (self.generate() / "index.md").read_text(encoding="utf-8")
        self.assertEqual(front_matter(text)["author"], "opus (fallback writer), MVP of the week, 103.0")
        body = text.split("---", 2)[2]
        self.assertIn("The MVP is claude-haiku-5-5, but no crew is recorded for it, so the fallback crew, opus, "
                      "writes this note's victory address.", body)
        self.assertIn("{{victory-address}} opus replaces this line", body)

    def test_a_frozen_day_without_a_model_rank_names_no_mvp(self):
        (self.frozen / "rank.json").unlink()
        text = (self.generate() / "index.md").read_text(encoding="utf-8")
        self.assertEqual(front_matter(text)["title"], "[Crew Ranking - 2026-11-09]: no MVP")
        self.assertIn("**No MVP this week:** the note froze no settled model rank for its date.", text)
        self.assertFalse((self.data / "2026-11-09" / "rank.json").exists())

    def test_monthly_award_and_weekly_boards_use_the_same_schedule_for_routing(self):
        for day, award in [("2026-11-30", False), ("2026-12-07", True),
                           ("2026-12-14", False), ("2027-01-04", True)]:
            with self.subTest(day=day):
                args = [day, *self.args[1:]]
                writer = json.loads(run(*args, "--writer-only").stdout)
                proc = run(*args)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                path = self.notes / f"crew-rankings-{day}" / "index.md"
                meta = build.parse(path)
                facts = json.loads((self.data / day / "facts.json").read_text())
                self.assertEqual(facts["writer"], writer)
                self.assertEqual(facts["award_period"], "month" if award else None)
                self.assertEqual(bool(facts["mvp"]), award)
                self.assertIn("crews-by-role:", meta["body"])
                self.assertEqual("{{victory-address}}" in meta["body"], award)
                self.assertEqual(writer["crew"], "sol" if award else "opus")
                if award:
                    self.assertIn("co-MVPs", meta["title"])
                    self.assertIn("MVP of the month", meta["authors"][0])
                else:
                    self.assertEqual(meta["title"], f"[Crew Ranking - {day}]")
                    self.assertNotIn("MVP", path.read_text())

    def test_monthly_award_without_a_qualified_board_has_no_winner_or_address(self):
        self.freeze(rank_board(*TIED_BAND, qualified=False))
        day = "2026-12-07"
        proc = run(day, *self.args[1:])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        meta = build.parse(self.notes / f"crew-rankings-{day}" / "index.md")
        self.assertIn("no MVP this month", meta["authors"][0])
        self.assertIn("model board has not qualified", meta["body"])
        self.assertNotIn("Victory address", meta["body"])

    def test_an_existing_note_is_not_overwritten_without_force(self):
        note = self.generate()
        (note / "index.md").write_text("written address", encoding="utf-8")
        proc = run(*self.args)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual((note / "index.md").read_text(encoding="utf-8"), "written address")
        self.generate("--force")

    def test_script_has_no_crown_or_live_request_left(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for gone in ("crown", "pool_models", "shrink", "K_SENSITIVITY", "CROWN_K", "--live"):
            self.assertNotIn(gone, source)
        self.assertIn('"--until"', source)


class FetchRank(unittest.TestCase):
    def raw(self, **overrides):
        return {**rank_board(HAIKU_ROW, LUNA_ROW), "window": "30d", "since": "2026-09-25T00:00:00Z",
                "until": "2026-10-25T00:00:00Z", "computed_at": "2026-11-09T00:00:00Z", **overrides}

    def test_fetch_asks_orbit_for_the_settled_board_at_the_note_date(self):
        with mock.patch.object(crew_rankings.snap, "orbit_json", return_value=self.raw()) as orbit:
            rank = crew_rankings.fetch_rank("orbit", "2026-11-09T00:00:00Z")
        self.assertEqual(orbit.call_args.args[0], ["agents", "rank", "--window", "30d", "--until", "2026-11-09T00:00:00Z"])
        self.assertEqual(orbit.call_args.args[1], "orbit")
        self.assertEqual((rank["live"], rank["provisional"], rank["qualified"], rank["scales_source"]),
                         (False, False, True, "season"))
        self.assertEqual(rank["rows"][0]["rank"], 1)

    def test_fetch_refuses_a_live_board(self):
        with mock.patch.object(crew_rankings.snap, "orbit_json", return_value=self.raw(live=True, provisional=True)):
            with self.assertRaises(SystemExit):
                crew_rankings.fetch_rank("orbit", "2026-11-09T00:00:00Z")


class CrewRankingBuild(unittest.TestCase):
    NOTE = """---
title: {title}
summary: The crew boards.
status: {status}
date: 2026-11-09
author: {author}
tags: rankings, weekly
---

{address}
"""

    def note(self, status, address, title="[Crew Ranking - 2026-11-09]: MVP sol",
             author="sol · effort unknown (gpt-6.1-sol), MVP of the week, 132.6", slug="crew-rankings-2026-11-09"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / slug / "index.md"
        path.parent.mkdir()
        path.write_text(self.NOTE.format(title=title, status=status, author=author, address=address), encoding="utf-8")
        return path

    def test_published_note_with_the_placeholder_fails_and_a_draft_builds(self):
        with self.assertRaises(SystemExit) as caught:
            build.parse(self.note("published", "{{victory-address}} sol writes here."))
        self.assertIn("victory address", str(caught.exception))
        draft = build.parse(self.note("draft", "{{victory-address}} sol writes here."))
        self.assertEqual(draft["status"], "draft")
        published = build.parse(self.note("published", "I landed the most."))
        self.assertEqual(published["authors"], ["sol · effort unknown (gpt-6.1-sol), MVP of the week, 132.6"])

    def test_a_published_byline_with_an_old_estimate_mark_still_builds(self):
        old = "sol@high (est.) (gpt-6.1-sol), MVP of the week, 132.6"
        self.assertEqual(build.parse(self.note("published", "I landed the most."))["authors"],
                         ["sol · effort unknown (gpt-6.1-sol), MVP of the week, 132.6"])
        path = self.note("published", "I landed the most.", author=old)
        self.assertEqual(build.parse(path)["authors"], [old])

    def test_the_co_mvp_fallback_and_no_mvp_bylines_build(self):
        co_mvp = "sol · effort unknown (gpt-6.1-sol), MVP of the week, 114.6"
        self.assertEqual(build.parse(self.note("published", "Text.", "[Crew Ranking - 2026-11-09]: co-MVPs a and b", co_mvp))["authors"], [co_mvp])
        fallback = "opus (fallback writer), no MVP this week"
        self.assertEqual(build.parse(self.note("published", "Text.", "[Crew Ranking - 2026-11-09]: no MVP", fallback))["authors"], [fallback])
        writes_for_mvp = "opus (fallback writer), MVP of the week, 114.6"
        self.assertEqual(build.parse(self.note("published", "Text.", "[Crew Ranking - 2026-11-09]: MVP a", writes_for_mvp))["authors"], [writes_for_mvp])

    def test_a_weekly_note_must_name_its_mvp_or_no_mvp_in_its_title_and_its_writer_in_its_byline(self):
        with self.assertRaises(SystemExit) as caught:
            build.parse(self.note("draft", "Text.", title="[Crew Ranking - 2026-11-09]: Weekly"))
        self.assertIn("MVP, co-MVPs or no MVP", str(caught.exception))
        with self.assertRaises(SystemExit) as caught:
            build.parse(self.note("draft", "Text.", author="Ann, Bo"))
        self.assertIn("fallback writer", str(caught.exception))

    def test_a_plain_note_keeps_its_comma_separated_authors(self):
        path = self.note("draft", "Text.", title="Plain note", author="Ann, Bo", slug="plain-note")
        self.assertEqual(build.parse(path)["authors"], ["Ann", "Bo"])

    def test_published_weekly_notes_still_build(self):
        for slug in ("crew-rankings-2026-11-03", "crew-rankings-2026-11-08"):
            with self.subTest(slug=slug):
                self.assertEqual(build.parse(ROOT / "notes" / slug / "index.md")["status"], "published")

    def test_embed_is_the_ranking_pages_stacked_crews_by_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "data" / "crew-rankings" / "2026-11-09"
            directory.mkdir(parents=True)
            (directory / "scorecards.json").write_text(json.dumps(fixtures.effort_scorecards()), encoding="utf-8")
            with mock.patch.object(build, "ROOT", Path(tmp)), mock.patch.object(build_notes, "ROOT", Path(tmp)):
                body = build.render_body("Intro.\n\n<!-- crews-by-role: data/crew-rankings/2026-11-09 -->\n\nLimits.\n")
                html, embedded = build.embed_crews_by_role(body, "note")
                self.assertTrue(embedded)
                self.assertIn('<div class="analytics crews-embed">\n' + build.render_crews_by_role(directory) + "\n</div>", html)
                self.assertNotIn("<!-- crews-by-role", html)
                self.assertEqual(build.embed_crews_by_role("<p>plain</p>", "note"), ("<p>plain</p>", False))
                for bad in ("data/analytics/2026-11-09", "data/crew-rankings/2026-11-10", "../x"):
                    with self.assertRaises(SystemExit):
                        build.embed_crews_by_role(f"<!-- crews-by-role: {bad} -->", "note")

    def test_method_note_states_the_top_band_rule_and_no_longer_splits_podium_and_mvp(self):
        text = (ROOT / "notes" / "crew-rankings-method" / "index.md").read_text(encoding="utf-8")
        self.assertIn("top tie band", text)
        self.assertIn("co-MVPs", text)
        self.assertNotIn("can name different", text)
        self.assertNotIn("rank-1 crew", text)


if __name__ == "__main__":
    unittest.main()
