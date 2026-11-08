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
        self.assertIn("80 runs", settled)
        self.assertIn("20 runs", settled)
        self.assertIn("80.00%", settled)
        self.assertIn("20.00%", settled)
        self.assertIn("Denominator: 100 runs", settled)
        self.assertIn("16.67%", failures)
        self.assertIn("8.33%", failures)
        self.assertIn("Denominator: 120 runs", failures)
        self.assertIn("120 recorded runs; 100 settled outcomes", document)
        self.assertIn('href="https://constellation-works.com/analytics/reliability/"', document)
        self.assertNotIn('href="/notes/" aria-current="page"', document)
        for element_id in ("settled", "failures", "other-outcomes"):
            board = section(document, element_id)
            self.assertIn(f'datetime="{SINCE}"', board)
            self.assertIn(f'datetime="{UNTIL}"', board)
            self.assertIn("UTC.", board)

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
        self.assertIn("100.00%", section(document, "other-outcomes"))

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
            with patch.object(build, "ROOT", root):
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

    def by_job_row(self, job_id, succeeded, failed, total=None, rate_value=None):
        counts = {"succeeded": succeeded, "failed": failed,
                  "total": succeeded + failed if total is None else total}
        row = {"job_id": job_id, "counts": counts}
        if rate_value is not None:
            row["failure_rate"] = {"value": rate_value, "denominator": 1,
                                   "numerator": 0, "denominator_label": "x"}
        return row

    def test_by_job_renders_bars_counts_rates_and_sort(self):
        data = fixture()
        data["by_job"] = [
            self.by_job_row("task_auto_pipeline", 90, 10, total=110, rate_value=0.99),
            self.by_job_row("task_pr_pipeline", 80, 20, total=120),
            self.by_job_row("task_gate_pipeline", 30, 20, total=60),
        ]
        original = copy.deepcopy(data)
        document = build.render_reliability_page(data, "2026-11-08")
        self.assertEqual(data, original)
        by_job = section(document, "by-job")
        # Human-readable labels, not raw ids for known jobs.
        self.assertIn("Auto delivery", by_job)
        self.assertIn("PR delivery", by_job)
        self.assertIn("Task gate", by_job)
        # Rates are recomputed from counts, never the supplied rate.
        self.assertIn("10.00%", by_job)
        self.assertIn("20.00%", by_job)
        self.assertIn("40.00%", by_job)
        self.assertNotIn("99.00%", by_job)
        # Failed/settled/total counts are shown.
        self.assertIn("10 failed of 100 settled (110 total)", by_job)
        self.assertIn("20 failed of 100 settled (120 total)", by_job)
        self.assertIn("20 failed of 50 settled (60 total)", by_job)
        # Sorted by failures then total, as the snapshot orders them.
        positions = [by_job.index(name) for name in ("PR delivery", "Task gate", "Auto delivery")]
        self.assertEqual(positions, sorted(positions))
        # Bars encode the rate alongside the text, not by colour alone.
        self.assertIn('class="hbar-plot"', by_job)
        self.assertIn('class="bar s-hard"', by_job)
        # Caption states the window scope.
        self.assertIn("30-day window", by_job)
        self.assertIn("all workspaces combined", by_job)

    def test_by_job_zero_support_is_unavailable(self):
        data = fixture()
        data["by_job"] = [self.by_job_row("task_auto_pipeline", 0, 0, total=5)]
        document = build.render_reliability_page(data, "2026-11-08")
        by_job = section(document, "by-job")
        self.assertIn("Unavailable", by_job)
        self.assertNotIn("0.00%", by_job)

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

    def test_by_job_disclosure_anchors_and_stylesheet(self):
        data = fixture()
        rows = [self.by_job_row(f"job_{index:02d}", 100 - index, index, total=100) for index in range(9)]
        data["by_job"] = rows
        document = build.render_reliability_page(data, "2026-11-08")
        by_job = section(document, "by-job")
        visible, disclosure = by_job.split('<details class="analytics-table-more">', 1)
        self.assertEqual(len(re.findall(r'class="hbar"', visible)), 7)
        self.assertIn("<summary>Show 2 more jobs</summary>", disclosure)
        self.assertEqual(len(re.findall(r'class="hbar"', disclosure)), 2)
        self.assertNotIn(" open", by_job.split("<details", 1)[0])
        # Seven or fewer rows keep the existing markup with no disclosure.
        data["by_job"] = rows[:7]
        short = build.render_reliability_page(data, "2026-11-08")
        self.assertNotIn("more jobs", section(short, "by-job"))
        # Section anchor exists and existing anchors are unchanged, in order.
        ids = re.findall(r'<section class="board" id="([^"]+)"', document)
        self.assertEqual(ids, ["settled", "by-job", "failures", "other-outcomes"])
        self.assertIn('<a href="#by-job">Failure rate by job</a>', document)
        self.assertIn('<a href="#settled">Success and failure</a>', document)
        self.assertIn('<a href="#failures">Failure categories</a>', document)
        self.assertIn('<a href="#other-outcomes">Other outcomes</a>', document)
        # The bars need the shared analytics stylesheet; no JavaScript is added.
        self.assertIn("/assets/analytics.css?v=", document)
        self.assertNotIn("fetch(", document)
        self.assertNotIn("/api/", document)


if __name__ == "__main__":
    unittest.main()
