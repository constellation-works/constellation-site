"""Reliability publication keeps aggregate math and private diagnostics separate."""

import copy
import json
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
        for row in data["by_job"]:
            self.assertNotIn(row["job_id"], document)
        self.assertIn(data["window"]["since"], document)
        self.assertIn(data["window"]["until"], document)


if __name__ == "__main__":
    unittest.main()
