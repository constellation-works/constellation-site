"""Monthly snapshot archives and the snapshot picker on each analytics page."""

import json
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
PAGES = ("metrics", "reliability", "experiments")


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
        build.build_ranking(root)
        analytics_page.build(root)
        build.build_reliability()
        build.build_experiments()


class MonthlyArchiveEntriesTest(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)

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
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)

    def test_build_renders_archives_for_all_pages_from_two_month_fixture(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
            root = make_root(tmp, ("2026-10-31", "2026-11-08", "2026-11-30", "2026-12-15"))
            build_all(root)
            # Every analytics view, including archives, keeps the original cascade order.
            pages = [root / "public" / "ranking" / "index.html"]
            pages.extend(page for slug in PAGES
                         for page in (root / "public" / "analytics" / slug).rglob("index.html"))
            for page in pages:
                document = page.read_text(encoding="utf-8")
                stylesheets = re.findall(r'href="(/assets/[^"?]+\.css)\?v=[0-9a-f]+"', document)
                self.assertEqual(stylesheets, [
                    "/assets/notes.css", "/assets/analytics.css", "/assets/analytics-ranking.css",
                ], str(page))
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

            # /ranking/ replaced the agents page: newest snapshot only, no archive.
            self.assertFalse((out / "agents").exists())
            ranking_dir = root / "public" / "ranking"
            self.assertEqual(sorted(path.name for path in ranking_dir.iterdir()), ["index.html"])
            ranking = (ranking_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn('Snapshot <time datetime="2026-12-15">2026-12-15</time>', ranking)
            self.assertNotIn("snapshot-picker", ranking)
            for gap in ("model unknown", "crew unknown", "crew unavailable", "ORB-", "/home/"):
                self.assertNotIn(gap, ranking)

            index = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn("Available months", index)
            self.assertIn("2026-11", index)
            for slug in PAGES:
                self.assertIn(f'href="/analytics/{slug}/2026-11/"', index, slug)
            self.assertNotIn("/analytics/agents/", index)

    def test_picker_and_banner_use_page_windows_or_label_fleet_reference(self):
        # Differing windows: reliability (2026-10-09..), a distinct metrics
        # durations window, a settled-reviewer window from the previous
        # month (2026-09-09.. in the real snapshot) and cumulative
        # experiments starting 2026-10-28/31. None may be conflated.
        reliability_since = "2026-10-09T17:22:36.488867042Z"
        reliability_until = "2026-11-08T17:22:36.488867042Z"
        metrics_since = "2026-10-05T00:00:00+00:00"
        metrics_until = "2026-11-04T00:00:00+00:00"
        with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
            root = make_root(tmp, ("2026-10-31", "2026-11-08", "2026-11-30", "2026-12-15"))
            for directory in (root / "data" / "analytics").iterdir():
                metrics_path = directory / "metrics.json"
                metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
                metrics["durations"]["window"]["since"] = metrics_since
                metrics["durations"]["window"]["until"] = metrics_until
                metrics_path.write_text(json.dumps(metrics), encoding="utf-8")

            latest_dir = root / "data" / "analytics" / "2026-12-15"
            self.assertEqual(
                analytics_page._window_stamps(latest_dir, "metrics"),
                (metrics_since, metrics_until),
            )
            self.assertEqual(
                analytics_page._window_stamps(latest_dir, "reliability"),
                (reliability_since, reliability_until),
            )
            self.assertEqual(
                analytics_page._window_stamps(latest_dir, "experiments"),
                (reliability_since, reliability_until),
            )

            build_all(root)
            out = root / "public" / "analytics"

            def banner(document):
                match = re.search(r'<p class="archive-banner">.*?</p>', document, re.S)
                self.assertIsNotNone(match)
                return match.group(0)

            expectations = {
                "experiments": ("fleet reliability reference window", reliability_since,
                                "each experiment shows its cumulative observation window"),
                "metrics": ("metrics window", metrics_since,
                            "a board prints its own window only where it differs"),
                "reliability": ("fleet reliability window", reliability_since, None),
            }
            for slug, (label, since, pointer) in expectations.items():
                live = (out / slug / "index.html").read_text(encoding="utf-8")
                archive = (out / slug / "2026-11" / "index.html").read_text(encoding="utf-8")
                for kind, picker, banner_html in (
                    ("live", picker_html(live), None),
                    ("archive", picker_html(archive), banner(archive)),
                ):
                    for fragment in (picker, banner_html):
                        if fragment is None:
                            continue
                        self.assertIn(label, fragment, (slug, kind))
                        if fragment == picker:
                            if slug == "metrics":
                                since_date = since[:10]
                                until_date = metrics_until[:10]
                            else:
                                since_date = since[:10]
                                until_date = reliability_until[:10]
                            self.assertIn(f"{since_date} to {until_date}", fragment, (slug, kind))
                        else:
                            self.assertIn(f'datetime="{since}"', fragment, (slug, kind))
                        self.assertNotIn(", window <time", fragment, (slug, kind))
                        if pointer:
                            self.assertIn(pointer, fragment, (slug, kind))
                    if slug == "reliability":
                        self.assertNotIn("reference window", picker, (slug, kind))
                    if slug == "metrics":
                        self.assertNotIn(f'datetime="{reliability_since}"', picker, (slug, kind))
                self.assertIn("2026-11-30", banner(archive), slug)
                self.assertIn("Historical snapshot", banner(archive), slug)

            # Each board's own period is preserved on the page body.
            ranking = (root / "public" / "ranking" / "index.html").read_text(encoding="utf-8")
            self.assertIn('datetime="2026-09-09T17:22:19Z"', ranking)
            experiments = (out / "experiments" / "index.html").read_text(encoding="utf-8")
            self.assertIn('datetime="2026-10-31T18:36:15.786740Z"', experiments)
            self.assertIn("Cumulative observations from experiment start", experiments)
            metrics_page = (out / "metrics" / "index.html").read_text(encoding="utf-8")
            self.assertIn(
                f'datetime="{metrics_since}" data-format="stamp" data-field="durations.window.since"',
                metrics_page,
            )

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

    def test_analytics_explanatory_blocks_use_their_full_container_width(self):
        def rule(css, selector):
            start = css.index(selector)
            return css[start:css.index("}", start) + 1]

        analytics_css = (ROOT / "public" / "assets" / "analytics.css").read_text(encoding="utf-8")
        notes_css = (ROOT / "public" / "assets" / "notes.css").read_text(encoding="utf-8")
        for css, selector in (
            (analytics_css, ".analytics .lede,"),
            (analytics_css, ".experiments .question-short {"),
            (analytics_css, ".experiments .exp-method ul {"),
            (analytics_css, ".analytics .warn {"),
            (analytics_css, ".analytics .role-banner {"),
            (analytics_css, ".analytics details.method ul {"),
            (notes_css, ".analytics .as-of,"),
            (notes_css, ".experiments .question {"),
        ):
            with self.subTest(selector=selector):
                self.assertIn("max-width: 100%", rule(css, selector))

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
        self.assertIn(".snapshot-picker, .snapshot-picker ul { gap: 4px; }", phone)
        self.assertNotIn("flex-direction: column", phone)
        # Theme tokens only, so the picker reads in light and dark alike.
        self.assertIn("var(--fg)", css[css.index(".snapshot-picker-label"):])


class WrongTypeWindowCandidatesTest(unittest.TestCase):
    """Non-object window candidates are ignored (ORB-23436)."""

    RELIABILITY_SINCE = "2026-10-09T17:22:36.488867042Z"
    RELIABILITY_UNTIL = "2026-11-08T17:22:36.488867042Z"
    METRICS_SINCE = "2026-10-05T00:00:00+00:00"
    METRICS_UNTIL = "2026-11-04T00:00:00+00:00"

    _MISSING = object()

    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)

    @property
    def valid_reliability(self):
        return {"since": self.RELIABILITY_SINCE, "until": self.RELIABILITY_UNTIL}

    @property
    def valid_metrics(self):
        return {"since": self.METRICS_SINCE, "until": self.METRICS_UNTIL}

    def _make_snapshot(self, tmp, *, meta_reliability=_MISSING, meta_metrics=_MISSING,
                       reliability_window=_MISSING, metrics_durations=_MISSING):
        directory = Path(tmp) / "2026-11-30"
        directory.mkdir(parents=True, exist_ok=True)
        windows = {}
        if meta_reliability is not self._MISSING:
            windows["reliability"] = meta_reliability
        if meta_metrics is not self._MISSING:
            windows["metrics"] = meta_metrics
        (directory / "meta.json").write_text(json.dumps({"windows": windows}), encoding="utf-8")
        if reliability_window is self._MISSING:
            (directory / "reliability.json").write_text(json.dumps({}), encoding="utf-8")
        else:
            (directory / "reliability.json").write_text(
                json.dumps({"window": reliability_window}), encoding="utf-8")
        if metrics_durations is self._MISSING:
            (directory / "metrics.json").write_text(json.dumps({}), encoding="utf-8")
        else:
            (directory / "metrics.json").write_text(
                json.dumps({"durations": metrics_durations}), encoding="utf-8")
        return directory

    def test_meta_reliability_wrong_type_falls_back_to_page_window(self):
        for bad in (["unexpected"], "unexpected", 42):
            with self.subTest(bad=bad):
                with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
                    directory = self._make_snapshot(
                        tmp, meta_reliability=bad, reliability_window=self.valid_reliability)
                    for page in ("reliability", "experiments", None):
                        self.assertEqual(
                            analytics_page._window_stamps(directory, page),
                            (self.RELIABILITY_SINCE, self.RELIABILITY_UNTIL),
                            (page, bad),
                        )

    def test_page_window_wrong_type_falls_back_to_meta(self):
        for bad in (["unexpected"], "unexpected", 42):
            with self.subTest(bad=bad):
                with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
                    directory = self._make_snapshot(
                        tmp, meta_reliability=self.valid_reliability, reliability_window=bad)
                    for page in ("reliability", "experiments", None):
                        self.assertEqual(
                            analytics_page._window_stamps(directory, page),
                            (self.RELIABILITY_SINCE, self.RELIABILITY_UNTIL),
                            (page, bad),
                        )

    def test_metrics_window_wrong_type_falls_back(self):
        for bad in (["unexpected"], "unexpected", 42):
            with self.subTest(kind="durations-window", bad=bad):
                with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
                    directory = self._make_snapshot(
                        tmp, meta_metrics=self.valid_metrics,
                        metrics_durations={"window": bad})
                    self.assertEqual(
                        analytics_page._window_stamps(directory, "metrics"),
                        (self.METRICS_SINCE, self.METRICS_UNTIL),
                    )
            with self.subTest(kind="durations-itself", bad=bad):
                with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
                    directory = self._make_snapshot(
                        tmp, meta_metrics=self.valid_metrics, metrics_durations=bad)
                    self.assertEqual(
                        analytics_page._window_stamps(directory, "metrics"),
                        (self.METRICS_SINCE, self.METRICS_UNTIL),
                    )
            with self.subTest(kind="meta-metrics", bad=bad):
                with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
                    directory = self._make_snapshot(
                        tmp, meta_metrics=bad,
                        metrics_durations={"window": self.valid_metrics})
                    self.assertEqual(
                        analytics_page._window_stamps(directory, "metrics"),
                        (self.METRICS_SINCE, self.METRICS_UNTIL),
                    )

    def test_all_candidates_malformed_returns_none(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
            directory = self._make_snapshot(
                tmp, meta_reliability=["unexpected"], reliability_window="unexpected")
            for page in ("reliability", "experiments", None):
                self.assertEqual(analytics_page._window_stamps(directory, page), (None, None), page)
                entry = analytics_page.snapshot_entry(directory, page)
                self.assertIsNone(entry["since"], page)
                self.assertIsNone(entry["until"], page)
                self.assertEqual(analytics_page._window_html(entry, page), "", page)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
            directory = self._make_snapshot(
                tmp, meta_metrics="unexpected", metrics_durations=["unexpected"])
            self.assertEqual(analytics_page._window_stamps(directory, "metrics"), (None, None))
            entry = analytics_page.snapshot_entry(directory, "metrics")
            self.assertEqual(analytics_page._window_html(entry, "metrics"), "")

    def test_build_all_with_malformed_meta_windows_still_renders(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
            root = make_root(tmp, ("2026-10-31", "2026-11-08", "2026-11-30", "2026-12-15"))
            archived = root / "data" / "analytics" / "2026-11-30"
            meta_path = archived / "meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["windows"]["reliability"] = ["unexpected"]
            meta["windows"]["metrics"] = "unexpected"
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            # Page payloads stay valid, so every page must still render.
            build_all(root)
            out = root / "public" / "analytics"
            for slug in PAGES:
                self.assertTrue((out / slug / "2026-11" / "index.html").is_file(), slug)
            live_experiments = (out / "experiments" / "index.html").read_text(encoding="utf-8")
            self.assertIn("fleet reliability reference window", picker_html(live_experiments))

    def test_experiments_archive_omits_window_when_all_candidates_malformed(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
            root = make_root(tmp, ("2026-10-31", "2026-11-08", "2026-11-30", "2026-12-15"))
            archived = root / "data" / "analytics" / "2026-11-30"
            meta_path = archived / "meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["windows"]["reliability"] = ["unexpected"]
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            reliability_path = archived / "reliability.json"
            reliability = json.loads(reliability_path.read_text(encoding="utf-8"))
            reliability["window"] = "unexpected"
            reliability_path.write_text(json.dumps(reliability), encoding="utf-8")
            entry = analytics_page.snapshot_entry(archived, "experiments")
            self.assertEqual((entry["since"], entry["until"]), (None, None))
            with patch.object(build, "ROOT", root):
                build.build_analytics_index()
                build.build_experiments()
            archive = (root / "public" / "analytics" / "experiments" / "2026-11" / "index.html").read_text(
                encoding="utf-8")
            self.assertIn("Historical snapshot", archive)
            banner = re.search(r'<p class="archive-banner">.*?</p>', archive, re.S).group(0)
            self.assertNotIn("fleet reliability reference window", banner)
            self.assertNotIn(f'datetime="{self.RELIABILITY_SINCE}"', banner)
            picker = picker_html(archive)
            item = picker.split('href="/analytics/experiments/2026-11/"')[1].split("</li>")[0]
            self.assertNotIn("fleet reliability reference window", item)
            self.assertNotIn(f'datetime="{self.RELIABILITY_SINCE}"', item)


if __name__ == "__main__":
    unittest.main()
