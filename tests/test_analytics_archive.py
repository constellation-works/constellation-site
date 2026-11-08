"""Monthly snapshot archives and the snapshot picker on each analytics page."""

import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import analytics_page
import build

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".orbit" / "tmp"
REAL = ROOT / "data" / "analytics" / "2026-11-08"
SNAPSHOT_FILES = ("scorecards.json", "metrics.json", "reliability.json", "experiments.json", "meta.json")
PAGES = ("agents", "metrics", "reliability", "experiments")


def make_root(tmp, days):
    root = Path(tmp)
    shutil.copytree(ROOT / "public" / "assets", root / "public" / "assets")
    for day in days:
        directory = root / "data" / "analytics" / day
        directory.mkdir(parents=True)
        for name in SNAPSHOT_FILES:
            shutil.copy2(REAL / name, directory / name)
    return root


def picker_html(document):
    match = re.search(r'<nav class="snapshot-picker".*?</nav>', document, re.S)
    if not match:
        raise AssertionError("page has no snapshot picker")
    return match.group(0)


def build_all(root):
    with patch.object(build, "ROOT", root):
        build.build_analytics_index()
        build.build_agents()
        analytics_page.build(root)
        build.build_reliability()
        build.build_experiments()


class MonthlyArchiveEntriesTest(unittest.TestCase):
    def test_latest_per_closed_month_with_floor_and_no_backfill(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
            base = Path(tmp) / "analytics"
            for day in ("2026-10-31", "2026-11-05", "2026-11-08", "2026-11-30",
                        "2026-12-01", "2026-12-15", "2027-01-10"):
                directory = base / day
                directory.mkdir(parents=True)
                (directory / "scorecards.json").write_text("{}", encoding="utf-8")
            entries = analytics_page.monthly_archive_entries(base, "scorecards.json")
            # Newest first; January is open (Latest), and nothing before the
            # 2026-11-08 floor becomes an entry, so 2026-11 is first overall.
            self.assertEqual([e["month"] for e in entries], ["2026-12", "2026-11"])
            self.assertEqual([e["date"] for e in entries], ["2026-12-15", "2026-11-30"])
            self.assertEqual(analytics_page.latest_snapshot_entry(base)["date"], "2027-01-10")

    def test_current_month_is_not_archived_until_it_ends(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
            base = Path(tmp) / "analytics"
            for day in ("2026-11-08", "2026-11-30"):
                directory = base / day
                directory.mkdir(parents=True)
                (directory / "metrics.json").write_text("{}", encoding="utf-8")
            # November has a month-end snapshot but no later snapshot yet:
            # it is still the live month, so the archive stays empty.
            self.assertEqual(analytics_page.monthly_archive_entries(base, "metrics.json"), [])


class ArchiveBuildTest(unittest.TestCase):
    def test_build_renders_archives_for_all_pages_from_two_month_fixture(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
            root = make_root(tmp, ("2026-10-31", "2026-11-08", "2026-11-30", "2026-12-15"))
            build_all(root)
            out = root / "public" / "analytics"
            for slug in PAGES:
                live = (out / slug / "index.html").read_text(encoding="utf-8")
                live_picker = picker_html(live)
                self.assertIn(f'href="/analytics/{slug}/" aria-current="page"', live_picker, slug)
                self.assertIn(f'href="/analytics/{slug}/2026-11/"', live_picker, slug)
                self.assertIn("2026-12-15", live_picker, slug)
                self.assertIn("2026-11-30", live_picker, slug)
                self.assertNotIn("/2026-10/", live_picker, slug)
                self.assertNotIn("/2026-12/", live_picker, slug)
                self.assertNotIn("<select", live_picker, slug)

                archive_path = out / slug / "2026-11" / "index.html"
                self.assertTrue(archive_path.is_file(), archive_path)
                archive = archive_path.read_text(encoding="utf-8")
                self.assertIn("Historical snapshot", archive, slug)
                self.assertIn("2026-11-30", archive, slug)
                self.assertIn(f'href="/analytics/{slug}/">Back to Latest</a>', archive, slug)
                self.assertIn(f"constellation-works.com/analytics/{slug}/2026-11/", archive, slug)
                archive_picker = picker_html(archive)
                self.assertIn(f'href="/analytics/{slug}/2026-11/" aria-current="page"', archive_picker, slug)
                self.assertLess(archive_picker.index("Latest"), archive_picker.index("2026-11"), slug)
                self.assertFalse((out / slug / "2026-10").exists(), slug)
                self.assertFalse((out / slug / "2026-12").exists(), slug)

            agents_archive = (out / "agents" / "2026-11" / "index.html").read_text(encoding="utf-8")
            self.assertIn("Snapshot 2026-11-30.", agents_archive)
            for gap in ("model unknown", "crew unknown", "crew unavailable", "ORB-", "/home/"):
                self.assertNotIn(gap, agents_archive)

            index = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn("Available months", index)
            self.assertIn("2026-11", index)
            for slug in PAGES:
                self.assertIn(f'href="/analytics/{slug}/2026-11/"', index, slug)

    def test_picker_shows_only_latest_until_november_ends(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
            root = make_root(tmp, ("2026-11-08", "2026-11-20"))
            build_all(root)
            out = root / "public" / "analytics"
            for slug in PAGES:
                live = (out / slug / "index.html").read_text(encoding="utf-8")
                self.assertIn("Latest", picker_html(live), slug)
                self.assertFalse((out / slug / "2026-11").exists(), slug)
            index = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn("No archived months yet", index)

    def test_picker_css_wraps_without_horizontal_scroll(self):
        css = (ROOT / "public" / "assets" / "notes.css").read_text(encoding="utf-8")
        self.assertIn(".snapshot-picker", css)
        self.assertIn(".archive-banner", css)
        picker = css[css.index(".snapshot-picker {"):]
        picker = picker[:picker.index("}")]
        for rule in ("flex-wrap: wrap", "max-width: 100%", "min-width: 0"):
            self.assertIn(rule, picker)
        self.assertIn("overflow-wrap: anywhere", css[css.index(".snapshot-picker li"):])
        phone = css[css.rindex("@media (max-width: 560px) {"):]
        self.assertIn(".snapshot-picker", phone)
        self.assertIn("flex-direction: column", phone)
        # Theme tokens only, so the picker reads in light and dark alike.
        self.assertIn("var(--fg)", css[css.index(".snapshot-picker-label"):])


if __name__ == "__main__":
    unittest.main()
