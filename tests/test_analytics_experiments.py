"""Concluded experiment publication from the daily, sanitized snapshot."""

import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import build


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".orbit" / "tmp"


def fixture():
    return {
        "schema_version": 1,
        "experiments": [{
            "name": "Lower cost with steady quality?",
            "hypothesis": "Can the treatment lower cost & preserve quality?",
            "status": "concluded",
            "started_at": "2026-10-01T01:02:03.123456789+00:00",
            "as_of": "2026-11-08T02:03:04.987654321Z",
            "concluded_arm": "treatment",
            "primary_metric": "cost_usd",
            "arms": [
                {"name": "control", "control": True, "n": 20,
                 "crew_mix": [{"crew": "sol", "tasks": 20}]},
                {"name": "treatment", "n": 18,
                 "crew_mix": [{"crew": "luna", "tasks": 18}]},
            ],
            "metrics": [{
                "metric": "cost_usd", "kind": "mean", "unit": "usd", "better": "lower",
                "differences": [{"arm": "treatment", "overall": {
                    "estimate": -2, "interval": [-3, -1]}}],
                "arms": [
                    {"arm": "control", "mean": 4, "mean_interval": [3, 5],
                     "median": 3.5, "median_interval": [2, 4],
                     "n": 20, "open": 0, "unmeasured": 0},
                    {"arm": "treatment", "mean": 2, "mean_interval": [1, 3],
                     "n": 18, "open": 1, "unmeasured": 2},
                ],
            }, {
                "metric": "delivery_done_rate", "kind": "rate", "unit": "rate", "better": "higher",
                "differences": [{"arm": "treatment", "overall": {"estimate": None}}],
                "arms": [
                    {"arm": "control", "mean": 0.9, "mean_interval": [0.7, 1],
                     "n": 20, "open": 0, "unmeasured": 0},
                    {"arm": "treatment", "mean": None, "n": 0, "open": 18,
                     "unmeasured": 0},
                ],
            }],
            "verdict": {"state": "inconclusive", "label": "inconclusive",
                        "arm": "control", "reasons": ["Quality interval straddles the limit."]},
        }],
    }


class ExperimentsPageTest(unittest.TestCase):
    def test_question_arms_outcomes_intervals_verdict_and_distinct_choice(self):
        data = fixture()
        original = copy.deepcopy(data)
        doc = build.render_experiments_page(data, "2026-11-08")
        self.assertEqual(data, original)
        for text in (
            "Can the treatment lower cost &amp; preserve quality?", "sol (20 tasks)",
            "luna (18 tasks)", "$4.00", "$3.00 – $5.00",
            "$3.50", "$2.00 – $4.00", "20 measured tasks",
            "1 open tasks; 2 unmeasured tasks", "90.0%", "70.0% – 100.0%",
            "<strong>Verdict:</strong> inconclusive.", "<strong>Chosen arm:</strong> treatment.",
            "Statistical recommendation: control.", "Quality interval straddles the limit.",
            "2026-10-01T01:02:03.123456789Z", "2026-11-08T02:03:04.987654321Z",
            "UTC.", "not a rolling 30-day window", "Raw per-arm outcomes",
            "Difference from control", "-$2.00, -$3.00 to -$1.00", "not measured",
            "treatment: -$2.00 difference from control", "better than control",
            'href="https://constellation-works.com/analytics/experiments/"',
        ):
            self.assertIn(text, doc)
        self.assertIn("Unavailable", doc)
        self.assertNotIn("0.0%", doc.split('data-label="Arm"><span class="value">treatment</span>')[-1])

    def test_exploratory_label_in_primary_and_secondary_outcomes(self):
        data = fixture()
        primary, secondary = data["experiments"][0]["metrics"]
        secondary["exploratory"] = True
        doc = build.render_experiments_page(data, "2026-11-08")
        self.assertIn("<h4>Delivery done rate (exploratory, not a decision metric)</h4>", doc)
        self.assertIn("<h4>Cost</h4>", doc)
        self.assertNotIn("Cost (exploratory", doc)

        primary["exploratory"] = True
        doc = build.render_experiments_page(data, "2026-11-08")
        self.assertIn("<h4>Cost (exploratory, not a decision metric)</h4>", doc)

    def test_only_concluded_lifecycle_even_if_verdict_claims_winner(self):
        data = fixture()
        for status in ("running", "paused", "draft", "abandoned", None, "Concluded"):
            other = copy.deepcopy(data["experiments"][0])
            other.update(status=status, name=f"omit-{status}")
            other["verdict"] = {"state": "winner", "arm": "treatment"}
            data["experiments"].append(other)
        doc = build.render_experiments_page(data, "2026-11-08")
        self.assertEqual(doc.count('<section class="board experiment"'), 1)
        self.assertNotIn("omit-", doc)
        data["experiments"][0]["verdict"] = {"state": "collecting"}
        data["experiments"][0]["concluded_arm"] = None
        doc = build.render_experiments_page(data, "2026-11-08")
        self.assertIn("<strong>Verdict:</strong> collecting.", doc)
        self.assertIn("<strong>Chosen arm:</strong> None recorded.", doc)

    def test_empty_snapshot_and_bad_schema_or_windows(self):
        self.assertIn("No concluded experiments", build.render_experiments_page(
            {"schema_version": 1, "experiments": []}, "2026-11-08"))
        for data in ([], {}, {"schema_version": True}, {"schema_version": 1, "experiments": {}}):
            with self.subTest(data=data), self.assertRaises(SystemExit):
                build.render_experiments_page(data, "2026-11-08")
        for stamp in (None, "not a date", "2026-10-32T00:00:00Z", "2026-10-01T00:00:00-07:00", "2027-01-01T00:00:00Z"):
            data = fixture()
            data["experiments"][0]["started_at"] = stamp
            with self.subTest(stamp=stamp), self.assertRaises(SystemExit):
                build.render_experiments_page(data, "2026-11-08")

    def test_unknown_fields_not_published_and_public_text_escaped(self):
        data = fixture()
        experiment = data["experiments"][0]
        private = "ORB-123 jrun-private dk-server-99 /home/private secret prompt"
        experiment.update(id=private, task_title=private, prompt=private, warnings=[private])
        experiment["arms"][0].update(run_id=private, usage={"secret": private})
        experiment["metrics"][0]["arms"][0]["diagnostic"] = private
        experiment["metrics"].append({"metric": private, "arms": []})
        experiment["arms"][0]["crew_mix"].extend([
            {"crew": "crew unavailable", "tasks": 80},
            {"crew": "crew unknown", "tasks": 80},
            {"crew": "legacy", "model": "model unknown", "tasks": 80},
        ])
        for key in ("name", "hypothesis"):
            experiment[key] = '<script>alert("x")</script>'
        experiment["verdict"]["reasons"] = ["<img src=x onerror=alert(1)>"]
        doc = build.render_experiments_page(data, "2026-11-08")
        for text in (private, "crew unavailable", "crew unknown", "model unknown", "<script>alert", "<img src=x"):
            self.assertNotIn(text, doc)
        self.assertIn("&lt;script&gt;", doc)
        self.assertIn("&lt;img", doc)

    def test_unavailable_and_zero_are_distinct(self):
        for value in (None, True, "5", float("nan"), float("inf")):
            self.assertEqual(build.experiment_value(value, "USD"), "Unavailable")
        self.assertEqual(build.experiment_value(0, "USD"), "$0.00")
        for interval in (None, [], [1], [2, 1], [False, 1], [0, float("inf")]):
            self.assertEqual(build.experiment_interval(interval, "USD"), "Unavailable")
        self.assertEqual(build.experiment_interval([0, 0], "USD"), "$0.00 – $0.00")

    def test_difference_chart_order_collapse_formatting_and_raw_hidden(self):
        data = fixture()
        exp = data["experiments"][0]
        exp["metrics"].append({
            "metric": "total_tokens", "kind": "mean", "unit": None, "better": "lower",
            "exploratory": True,
            "differences": [{"arm": "treatment", "overall": {
                "estimate": 13097061.69, "interval": [8994127.15, 17750050.23]}}],
            "arms": [{"arm": "control", "mean": 1, "n": 1}, {"arm": "treatment", "mean": 2, "n": 1}],
        })
        exp["metrics"].append({
            "metric": "implement_duration", "kind": "mean", "unit": "minutes", "better": "lower",
            "exploratory": True,
            "differences": [{"arm": "treatment", "overall": {"estimate": 38.5}}],
            "arms": [{"arm": "control", "mean": 1, "n": 1}, {"arm": "treatment", "mean": 2, "n": 1}],
        })
        doc = build.render_experiments_page(data, "2026-11-08")
        # Primary (cost) before guardrail (delivery rate), exploratory collapsed.
        self.assertLess(doc.index(">Cost <"), doc.index("Delivery done rate"))
        self.assertIn('<span class="diff-kind">Primary</span>', doc)
        self.assertIn('<span class="diff-kind">Guardrail</span>', doc)
        self.assertIn("<summary>Other metrics (2)</summary>", doc)
        self.assertIn("+13.1M tokens", doc)
        self.assertIn("+38.5 min, interval unavailable", doc)
        self.assertNotIn("13,097,061.69", doc)
        self.assertNotIn("13097061", doc)
        # Rate differences are points; the fixture rate arm is unmeasured.
        rate = {"metric": "delivery_done_rate", "unit": "rate", "better": "higher"}
        self.assertEqual(build.experiment_difference(0.25, rate), "+25.0 points")
        self.assertEqual(build.experiment_difference(11.64, exp["metrics"][0]), "+$11.64")
        # Raw tables live only inside the collapsed raw block.
        before_raw, _, raw = doc.partition('<details class="experiment-raw">')
        self.assertNotIn("<table", before_raw)
        self.assertIn("<table", raw)
        self.assertIn("$4.00", raw)
        # Chart itself needs no script and every measured row carries a text equivalent.
        chart = doc.partition('<div class="diff-chart">')[2].partition('<details class="experiment-raw">')[0]
        self.assertNotIn("<script", chart)
        self.assertIn('class="sr-only">treatment:', chart)

    def test_small_generic_differences_never_render_signed_zero(self):
        import re

        lead = {"metric": "lead_time_per_line", "unit": None, "better": "lower"}
        repairs = {"metric": "review_repairs", "unit": None, "better": "lower"}
        # Live-snapshot magnitudes must keep a non-zero signed value.
        self.assertEqual(
            build.experiment_difference(-0.0006036, lead), "-0.0006 hours/line")
        self.assertEqual(
            build.experiment_difference(0.001606, lead), "+0.0016 hours/line")
        self.assertEqual(
            build.experiment_difference(-0.0011446, repairs), "-0.0011 repairs/task")
        self.assertEqual(
            build.experiment_difference_interval(
                [-0.0018127530072524732, 0.0008361674274996601], lead),
            "-0.0018 hours/line to +0.0008 hours/line")
        # Small per-arm means also stay non-zero through experiment_value.
        self.assertEqual(
            build.experiment_value(0.0018687083846129571, "hours/line"),
            "0.0019 h / line")
        signed_zero = re.compile(r"[+-]0(?![\d.])")
        for text in (
            build.experiment_difference(-0.0006036, lead),
            build.experiment_difference(0.001606, lead),
            build.experiment_difference(0.0002473267980663391, lead),
            build.experiment_difference(-0.001082881708263405, lead),
            build.experiment_difference(-0.0011446, repairs),
            build.experiment_difference_interval(
                [-0.04502442002442002, 0.042353479853479856], repairs),
            build.experiment_value(0.0018687083846129571, "hours/line"),
        ):
            self.assertIsNone(signed_zero.search(text), text)
        # Magnitudes far below 0.00005 never collapse to zero either.
        for tiny in (5e-06, 1e-09):
            for metric in (lead, repairs):
                text = build.experiment_difference(tiny, metric)
                self.assertIsNone(signed_zero.search(text), text)
                text = build.experiment_difference(-tiny, metric)
                self.assertIsNone(signed_zero.search(text), text)
        # True zeros stay unsigned.
        self.assertEqual(build.experiment_difference(0, repairs), "0 repairs/task")
        self.assertEqual(build.experiment_difference(0.0, lead), "0 hours/line")

    def test_committed_snapshot_has_no_signed_zero_diffs(self):
        import re

        directory = build.latest_analytics_dir()
        data = json.loads((directory / "experiments.json").read_text())
        doc = build.render_experiments_page(data, directory.name)
        signed_zero = re.compile(r"[+-]0(?![\d.])")
        chart = doc.partition('<div class="diff-chart">')[2]
        self.assertIsNone(signed_zero.search(chart))

    def test_difference_without_arm_entry_is_not_measured(self):
        data = fixture()
        data["experiments"][0]["metrics"][0]["differences"] = []
        doc = build.render_experiments_page(data, "2026-11-08")
        chart = doc.partition('<div class="diff-chart">')[2].partition('<details class="experiment-raw">')[0]
        self.assertIn("not measured", chart)

    def test_build_newest_and_refuse_missing_or_invalid_newest(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as temp:
            root = Path(temp)
            shutil.copytree(ROOT / "public" / "assets", root / "public" / "assets")
            for day in ("2026-11-07", "2026-11-08"):
                directory = root / "data" / "analytics" / day
                directory.mkdir(parents=True)
                (directory / "scorecards.json").write_text("{}")
                data = fixture()
                data["experiments"][0]["name"] = f"Experiment from {day}"
                (directory / "experiments.json").write_text(json.dumps(data))
            with patch.object(build, "ROOT", root):
                build.build_experiments()
                output = root / "public" / "analytics" / "experiments" / "index.html"
                self.assertIn("Experiment from 2026-11-08", output.read_text())
                self.assertNotIn("Experiment from 2026-11-07", output.read_text())
                latest = directory / "experiments.json"
                for content in ("invalid JSON", '{}'):
                    latest.write_text(content)
                    with self.assertRaises(SystemExit):
                        build.build_experiments()
                latest.unlink()
                with self.assertRaises(SystemExit):
                    build.build_experiments()
                latest.write_text('{"schema_version": 1, "experiments": []}')
                build.build_experiments()
                self.assertIn("No concluded experiments", output.read_text())
                self.assertNotIn("Experiment from", output.read_text())

    def test_committed_snapshot_all_concluded_sections(self):
        directory = build.latest_analytics_dir()
        data = json.loads((directory / "experiments.json").read_text())
        doc = build.render_experiments_page(data, directory.name)
        concluded = [x for x in data["experiments"] if x["status"] == "concluded"]
        self.assertEqual(doc.count('<section class="board experiment"'), len(concluded))
        for experiment in concluded:
            self.assertIn(build.html.escape(experiment["hypothesis"]), doc)
            for arm in experiment["arms"]:
                self.assertIn(arm["name"], doc)
            self.assertNotIn(experiment["id"], doc)
        self.assertNotIn("hard-tier-explore-first", doc)
        by_model = next(x for x in concluded if x["name"] == "hard-tier-by-model")
        self.assertEqual(by_model["primary_metric"], "cost_usd")
        section = doc.split("<h2>" + build.html.escape(by_model["name"]), 1)[1].split("\n</section>", 1)[0]
        self.assertIn("<h3>Difference from control</h3>", section)
        self.assertIn('<details class="experiment-raw"><summary>Raw per-arm outcomes</summary>', section)
        chart, _, raw = section.partition('<details class="experiment-raw">')
        self.assertNotIn("<table", chart)
        self.assertIn("<table", raw)
        self.assertIn("Other metrics (", chart)
        for metric in by_model["metrics"]:
            if metric["metric"] not in build.EXPERIMENT_METRICS:
                continue
            label = build.EXPERIMENT_METRICS[metric["metric"]][0]
            suffix = " (exploratory, not a decision metric)" if metric.get("exploratory") else ""
            self.assertIn(f"<h4>{label}{suffix}</h4>", raw)
        for text in ("ORB-", "jrun-", "/home/", "dk-server", "dropped"):
            self.assertNotIn(text, doc)


if __name__ == "__main__":
    unittest.main()
