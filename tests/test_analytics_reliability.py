"""Reliability publication keeps aggregate math and private diagnostics separate."""

import copy
import html
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build
import build_common
import build_reliability


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".orbit" / "tmp"
SINCE = "2026-10-09T09:12:03.585033649Z"
UNTIL = "2026-11-08T09:12:03.585033649Z"


def fixture():
    counts = {key: 0 for key, _label in build.RELIABILITY_OUTCOMES}
    counts.update(succeeded=80, failed=20, cascaded=10, held=10, total=120)
    return {
        "schema_version": 1,
        "window": {"label": "30d", "since": SINCE, "until": UNTIL},
        "totals": {"job_runs": {"counts": counts}},
    }


def section(document, element_id):
    return document.split(f'id="{element_id}"', 1)[1].split("</section>", 1)[0]


class ReliabilityTests(unittest.TestCase):
    def test_rates_use_the_documented_denominators(self):
        data = fixture()
        # Deliberately wrong supplied rate: the page must use count arithmetic.
        data["totals"]["job_runs"]["failure_rate"] = {"value": .999}
        document = build.render_reliability_page(data, "2026-11-08")
        settled = section(document, "settled")
        failures = section(document, "failures")
        self.assertIn('<span class="rel-big">80.00%</span>', settled)
        self.assertIn("80 of 100", settled)
        self.assertIn("failed directly", settled)
        self.assertNotIn("99.9", document)
        # Where every run ended: shares of all 120 recorded runs.
        self.assertIn("Share of all 120 recorded runs", failures)
        self.assertIn("80 · 66.67%", failures)
        self.assertIn("20 · 16.67%", failures)
        self.assertIn("10 · 8.33%", failures)
        self.assertIn('class="mix-bar" role="img"', failures)
        self.assertIn("80 runs", failures)
        self.assertIn("120 recorded runs; 100 settled outcomes", document)
        self.assertIn('href="https://constellation-works.com/analytics/reliability/"', document)
        self.assertNotIn('href="/notes/" aria-current="page"', document)
        self.assertIn(f'datetime="{SINCE}"', document)
        self.assertIn(f'datetime="{UNTIL}"', document)
        # Old anchors keep landing on the matching content.
        for element_id in ("settled", "failures", "other-outcomes", "by-job", "daily", "method"):
            self.assertIn(f'id="{element_id}"', document)

    def test_headline_tiles_use_recovery_counts(self):
        data = fixture()
        data["totals"]["recovery"] = {"per_job_run": {"numerator": 5, "denominator": 40, "value": 0.9}}
        data["totals"]["job_runs"]["counts"].update(cancelled=3, in_flight=2, upgrade_paused=1, held=4)
        data["totals"]["job_runs"]["counts"]["total"] = 80 + 20 + 10 + 3 + 2 + 1 + 4
        document = build.render_reliability_page(data, "2026-11-08")
        settled = section(document, "settled")
        self.assertIn("12.5%", settled)
        self.assertIn("5 of 40 job runs with steps", settled)
        self.assertIn("4 held · 3 cancelled · 3 paused or in flight", settled)
        for bad in ({"numerator": 5, "denominator": 0}, {"numerator": True, "denominator": 4},
                    {"numerator": 9, "denominator": 4}, "x"):
            data["totals"]["recovery"] = {"per_job_run": bad}
            self.assertIn("Unavailable", section(build.render_reliability_page(data, "2026-11-08"), "settled"))

    def test_private_fields_and_arbitrary_labels_have_no_output_route(self):
        data = fixture()
        secret = "ORB-99123 jrun-private host-private /home/private failure message <script>alert(1)</script>"
        data.update(source=secret, by_job=[{"job_id": secret}], activities=[{"activity_id": secret}],
                    observed_states={secret: 123}, failure_categories=[{"label": secret, "count": 123}],
                    metadata={"dropped": secret}, message=secret)
        data["window"]["bucket"] = secret
        data["totals"]["job_runs"]["counts"][secret] = 100
        data["totals"]["job_runs"]["failure_rate"] = {"denominator_label": secret}
        data["totals"]["recovery"] = {"message": secret}
        document = build.render_reliability_page(data, "2026-11-08")
        for forbidden in (secret, "ORB-", "jrun-", "host-private", "/home/", "failure message", "alert(1)"):
            self.assertNotIn(forbidden, document)
        self.assertNotIn("fetch(", document)
        self.assertNotIn("/api/", document)

    def test_zero_support_is_unavailable_rather_than_perfect_success(self):
        data = fixture()
        data["totals"]["job_runs"]["counts"] = {
            key: 0 for key in data["totals"]["job_runs"]["counts"]
        }
        document = build.render_reliability_page(data, "2026-11-08")
        self.assertIn("No recorded runs", document)
        self.assertIn("Unavailable", document)
        self.assertNotIn("0.00%", document)
        # All held: settled rates still have no denominator.
        data["totals"]["job_runs"]["counts"].update(held=10, total=10)
        document = build.render_reliability_page(data, "2026-11-08")
        self.assertIn("Unavailable", section(document, "settled"))
        self.assertIn("10 · 100.00%", section(document, "failures"))

    def test_refuses_unsafe_or_invalid_required_fields(self):
        changes = (
            ("schema_version", 2), ("schema_version", True),
            ("window", {"label": "7d", "since": SINCE, "until": UNTIL}),
            ("window", {"label": "30d", "since": "/home/private", "until": UNTIL}),
            ("window", {"label": "30d", "since": "2026-02-30T00:00:00Z", "until": UNTIL}),
            ("window", {"label": "30d", "since": UNTIL, "until": SINCE}),
            ("window", {"label": "30d", "since": SINCE, "until": "2026-11-07T09:12:03Z"}),
            ("totals", {}),
        )
        for key, value in changes:
            with self.subTest(key=key, value=value):
                data = fixture()
                data[key] = value
                with self.assertRaises(SystemExit):
                    build.render_reliability_page(data, "2026-11-08")
        for value in ("ORB-123", True, -1, 1.5, None):
            with self.subTest(count=value):
                data = fixture()
                data["totals"]["job_runs"]["counts"]["failed"] = value
                with self.assertRaises(SystemExit):
                    build.render_reliability_page(data, "2026-11-08")
        data = fixture()
        data["totals"]["job_runs"]["counts"]["total"] = 121
        with self.assertRaises(SystemExit):
            build.render_reliability_page(data, "2026-11-08")

    def test_build_uses_newest_snapshot_and_refuses_incomplete_latest(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "public" / "assets", root / "public" / "assets")
            for day in ("2026-11-07", "2026-11-08"):
                directory = root / "data" / "analytics" / day
                directory.mkdir(parents=True)
                (directory / "scorecards.json").write_text("{}")
                data = fixture()
                if day == "2026-11-07":
                    data["totals"]["job_runs"]["counts"].update(succeeded=70, failed=30)
                (directory / "reliability.json").write_text(json.dumps(data))
            with patch.object(build, "ROOT", root), patch.object(build_common, "ROOT", root), \
                    patch.object(build_reliability, "ROOT", root):
                build.build_reliability()
                document = (root / "public" / "analytics" / "reliability" / "index.html").read_text()
                self.assertIn("Snapshot 2026-11-08", document)
                self.assertIn("80.00%", document)
                self.assertNotIn("70.00%", document)
                # A new incomplete snapshot must not silently reuse yesterday's data.
                newest = root / "data" / "analytics" / "2026-11-09"
                newest.mkdir()
                (newest / "scorecards.json").write_text("{}")
                with self.assertRaises(SystemExit):
                    build.build_reliability()
                (newest / "reliability.json").write_text("invalid json")
                with self.assertRaises(SystemExit):
                    build.build_reliability()

    def test_committed_snapshot_renders_known_counts_only(self):
        directory = build.latest_analytics_dir()
        data = json.loads((directory / "reliability.json").read_text())
        original = copy.deepcopy(data)
        document = build.render_reliability_page(data, directory.name)
        self.assertEqual(data, original)
        counts = data["totals"]["job_runs"]["counts"]
        for key, _label in build.RELIABILITY_OUTCOMES:
            self.assertIn(f'{counts[key]:,} runs', document)
        jobs = build.reliability_by_job(data)
        self.assertEqual(len(jobs), len(data["by_job"]))
        for row in data["by_job"]:
            label = build.JOB_LABELS.get(row["job_id"], row["job_id"])
            self.assertIn(html.escape(label), document)
        self.assertIn(data["window"]["since"], document)
        self.assertIn(data["window"]["until"], document)

    def by_job_row(self, job_id, succeeded, failed, total=None, rate_value=None, low=None):
        counts = {"succeeded": succeeded, "failed": failed,
                  "total": succeeded + failed if total is None else total}
        row = {"job_id": job_id, "counts": counts}
        if rate_value is not None or low is not None:
            row["failure_rate"] = {"value": rate_value, "denominator": 1,
                                   "numerator": 0, "denominator_label": "x", "low_sample": low}
        return row

    def test_by_job_renders_bars_counts_rates_and_sort(self):
        data = fixture()
        data["by_job"] = [
            self.by_job_row("task_auto_pipeline", 90, 10, total=110, rate_value=0.99),
            self.by_job_row("task_pr_pipeline", 80, 20, total=120),
            self.by_job_row("task_gate_pipeline", 30, 20, total=60),
            self.by_job_row("ux_rules_pipeline", 5, 10, low=True),
            self.by_job_row("store_gc_pipeline", 8, 0, low=True),
            self.by_job_row("worktree_gc_pipeline", 400, 0),
        ]
        original = copy.deepcopy(data)
        document = build.render_reliability_page(data, "2026-11-08")
        self.assertEqual(data, original)
        by_job = section(document, "by-job")
        # Human-readable labels, not raw ids for known jobs.
        for label in ("Auto delivery", "PR delivery", "Task gate", "UX rules"):
            self.assertIn(label, by_job)
        # Rates are recomputed from counts, never the supplied rate.
        self.assertIn(">10.0%<", by_job)
        self.assertIn(">20.0%<", by_job)
        self.assertIn(">40.0%<", by_job)
        self.assertNotIn("99.0", by_job)
        # Failed and settled counts are shown.
        self.assertRegex(by_job, r'data-label="Failed">20</td><td class="num" data-label="Settled runs">50<')
        # Count order as the snapshot orders them; data for the rate sort.
        positions = [by_job.index(name) for name in ("PR delivery", "Task gate", "Auto delivery", "UX rules")]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('data-rate="0.400000" data-low="0"', by_job)
        self.assertIn('data-low="1"', by_job)
        self.assertIn("small sample", by_job)
        self.assertIn("PR delivery accounts for", by_job)
        # Zero-failure jobs fold into one disclosure with their settled runs.
        folded = by_job[by_job.index("<details"):]
        self.assertIn("2 jobs with no failures", folded)
        self.assertIn("Store GC (8)", folded)
        self.assertIn("Worktree GC (400)", folded)
        self.assertNotIn("Store GC", by_job[:by_job.index("<details")])
        # The sort control is progressive enhancement.
        self.assertIn('class="board-toggle job-sort" role="group" aria-label="Sort jobs" hidden', by_job)
        self.assertIn("all workspaces combined", by_job)
        jobs = build.reliability_by_job(data)
        self.assertEqual([job["low"] for job in jobs if job["job_id"] == "ux_rules_pipeline"], [True])

    def test_by_job_zero_support_is_unavailable(self):
        data = fixture()
        data["by_job"] = [self.by_job_row("task_auto_pipeline", 0, 0, total=5)]
        document = build.render_reliability_page(data, "2026-11-08")
        by_job = section(document, "by-job")
        self.assertIn("No job failures in this window.", by_job)
        self.assertNotIn("0.00%", by_job)
        self.assertEqual(build.reliability_by_job(data)[0]["rate"], None)
        self.assertEqual(build.short_pct(None), "Unavailable")

    def test_by_job_fallback_and_unsafe_ids(self):
        data = fixture()
        data["by_job"] = [
            self.by_job_row("custom_job+1", 90, 10),
            self.by_job_row("task_auto_pipeline", 90, 5),
            {"job_id": "bad <script>alert(1)</script>", "counts": {"succeeded": 1, "failed": 1, "total": 2}},
            {"job_id": "task_pr_pipeline", "counts": {"succeeded": True, "failed": 1, "total": 2}},
            {"job_id": "task_gate_pipeline", "counts": {"succeeded": 1, "failed": -1, "total": 0}},
        ]
        document = build.render_reliability_page(data, "2026-11-08")
        by_job = section(document, "by-job")
        # Unknown safe ids fall back to the raw id.
        self.assertIn(html.escape("custom_job+1"), by_job)
        self.assertIn("Auto delivery", by_job)
        # Unsafe ids and invalid counts never reach the page.
        self.assertNotIn("alert(1)", document)
        self.assertNotIn("bad", by_job)
        self.assertNotIn("PR delivery", by_job)
        self.assertNotIn("Task gate", by_job)
        self.assertNotIn("fetch(", document)
        self.assertNotIn("/api/", document)

    def test_daily_series_marks_partial_days_and_recomputes_rates(self):
        data = fixture()

        def bucket(day, succeeded, failed, rate=0.5):
            counts = {key: 0 for key, _label in build.RELIABILITY_OUTCOMES}
            counts.update(succeeded=succeeded, failed=failed, total=succeeded + failed)
            return {"bucket_start": f"2026-{day}T00:00:00Z", "bucket_end": None, "counts": counts,
                    "failure_rate": {"value": rate}}

        days = [bucket("10-09", 90, 10), bucket("10-10", 99, 1), bucket("10-11", 0, 0),
                bucket("11-07", 70, 30), bucket("11-08", 95, 5)]
        ends = ["2026-10-10", "2026-10-11", "2026-10-12", "2026-11-08", "2026-11-09"]
        for row, end in zip(days, ends):
            row["bucket_end"] = f"{end}T00:00:00Z"
        bad = bucket("10-12", 1, 1)
        bad["bucket_end"] = "2026-10-13T00:00:00Z"
        bad["counts"]["failed"] = -1
        unsafe = bucket("10-13", 1, 1)
        unsafe["bucket_start"] = "<script>"
        data["over_time"] = list(reversed(days)) + [bad, unsafe, "x"]
        series = build.reliability_days(data, SINCE, UNTIL)
        self.assertEqual([day["start"][:10] for day in series],
                         ["2026-10-09", "2026-10-10", "2026-10-11", "2026-11-07", "2026-11-08"])
        self.assertEqual([day["partial"] for day in series], [True, False, False, False, True])
        self.assertEqual([day["rate"] for day in series], [0.1, 0.01, None, 0.3, 0.05])
        self.assertEqual([day["settled"] for day in series], [100, 100, 0, 100, 100])

        document = build.render_reliability_page(data, "2026-11-08")
        daily = section(document, "daily")
        self.assertNotIn("<script>", document)
        # One bar per valid day with its own text alternative.
        self.assertEqual(len(re.findall(r'<li class="day', daily)), 5)
        self.assertIn('title="9 Oct: 10.00% · 10 failed of 100 settled (partial day)"', daily)
        self.assertIn("11 Oct: unavailable, no settled runs", daily)
        self.assertIn('<li class="day is-partial" title="9 Oct', daily)
        # A spike is at least 1.5x the 30-day rate (and at least 5%).
        self.assertIn('<li class="day is-spike" title="7 Nov', daily)
        self.assertIn("Labelled bars are at least 30.0%.", daily)
        # Reference line at the 30-day rate (20 of 100 settled).
        self.assertIn('class="day-ref"', daily)
        self.assertIn("<span>20.00%</span>", daily)
        self.assertIn("30-day rate 20.00%", daily)
        # Spike labels sit on days at or above the threshold only.
        self.assertIn('<span class="day-label" aria-hidden="true">30.0%</span>', daily)
        self.assertNotIn('<span class="day-label" aria-hidden="true">1.00%</span>', daily)
        # Volume strip and the table fallback, newest first.
        self.assertEqual(len(re.findall(r'style="height:', daily.split('class="day-vols"', 1)[1].split("</div>", 1)[0])), 5)
        table = daily[daily.index("Daily figures as a table"):]
        self.assertLess(table.index("8 Nov"), table.index("9 Oct"))
        self.assertIn("Faded: partial days (9 Oct and 8 Nov)", daily)

    def test_daily_series_absent_is_empty_not_an_error(self):
        document = build.render_reliability_page(fixture(), "2026-11-08")
        self.assertIn("No daily buckets in this window.", section(document, "daily"))

    def test_committed_snapshot_daily_series(self):
        directory = build.latest_analytics_dir()
        data = json.loads((directory / "reliability.json").read_text())
        since, until = data["window"]["since"], data["window"]["until"]
        series = build.reliability_days(data, since, until)
        self.assertEqual(len(series), len(data["over_time"]))
        self.assertTrue(series[0]["partial"])
        self.assertTrue(series[-1]["partial"])
        self.assertFalse(any(day["partial"] for day in series[1:-1]))
        for day, row in zip(series, data["over_time"]):
            self.assertEqual(day["settled"], row["failure_rate"]["denominator"])
            self.assertAlmostEqual(day["rate"], row["failure_rate"]["value"])

    def test_stylesheet_and_value_cells_stay_body_text(self):
        data = fixture()
        data["by_job"] = [self.by_job_row("task_auto_pipeline", 80, 20)]
        document = build.render_reliability_page(data, "2026-11-08")
        self.assertIn("/assets/analytics.css?v=", document)
        self.assertIn("/assets/analytics.js?v=", document)
        self.assertNotIn("fetch(", document)
        self.assertNotIn("/api/", document)
        failures = section(document, "failures")
        self.assertIn('<span class="value">', failures)
        # No stylesheet loaded by this page may turn table .value cells into
        # headline-size blocks: a headline-scale .value rule must be scoped to .score.
        linked = re.findall(r'href="(/assets/[^"]+\.css)(?:\?[^"]*)?"', document)
        self.assertTrue(linked)
        for href in linked:
            css = (ROOT / "public" / href.split("?")[0].lstrip("/")).read_text()
            for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
                selectors, declarations = match.group(1), match.group(2)
                if not re.search(r"\.value(?![-\w])", selectors):
                    continue
                if not re.search(
                    r"font-size\s*:\s*(clamp\s*\(\s*(2[4-9]|[3-9]\d)px|"
                    r"(2[4-9]|[3-9]\d)(\.\d+)?px)",
                    declarations,
                ):
                    continue
                for selector in selectors.split(","):
                    if re.search(r"\.value(?![-\w])", selector):
                        self.assertIn(".score", selector, msg=selector.strip())


if __name__ == "__main__":
    unittest.main()
