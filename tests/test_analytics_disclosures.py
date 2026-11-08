"""Shared disclosure behavior for public analytics tables."""

import json
import re
import unittest
from pathlib import Path

import analytics_page
import build


ROOT = Path(__file__).resolve().parents[1]


class AnalyticsDisclosureTests(unittest.TestCase):
    def test_seven_or_fewer_rows_keep_the_existing_metrics_markup(self):
        expected = (
            '<div class="table"><table><caption>Recent</caption>'
            '<thead><tr><th scope="col">Value</th></tr></thead>'
            '<tbody><tr><td data-label="Value">one</td></tr></tbody></table></div>'
        )
        self.assertEqual(analytics_page.table("Recent", ["Value"], [["<td>one</td>"]]), expected)
        seven_rows = [[f"<td>{index}</td>"] for index in range(1, 8)]
        expected_seven = (
            '<div class="table"><table><caption>Recent</caption>'
            '<thead><tr><th scope="col">Value</th></tr></thead><tbody>'
            + "".join(f'<tr><td data-label="Value">{index}</td></tr>' for index in range(1, 8))
            + '</tbody></table></div>'
        )
        self.assertEqual(analytics_page.table("Recent", ["Value"], seven_rows), expected_seven)

    def test_long_metrics_table_keeps_first_seven_rows_and_discloses_the_tail(self):
        rows = [[f"<td>{index}</td>"] for index in range(1, 10)]
        rendered = analytics_page.table("Daily", ["Day"], rows, more_label="days")
        visible, disclosure = rendered.split('<details class="analytics-table-more">', 1)
        self.assertEqual(re.findall(r"<td data-label=\"Day\">(\d+)</td>", visible), [str(i) for i in range(1, 8)])
        self.assertIn("<summary>Show 2 more days</summary>", disclosure)
        self.assertEqual(re.findall(r"<td data-label=\"Day\">(\d+)</td>", disclosure), ["8", "9"])
        self.assertNotIn(" open", rendered)

    def test_agents_and_experiment_tables_use_the_shared_disclosure(self):
        rows = [
            {"rank": index + 1, "crew": f"crew-{index}", "model": "model", "score": 100, "units": 10}
            for index in range(9)
        ]
        board = {
            "unit": "tasks", "rows": rows, "title": "Implementers", "min_support": 1,
        }
        agents = build.render_table(board)
        self.assertIn("<summary>Show 2 more entries</summary>", agents)
        visible, tail = agents.split('<details class="analytics-table-more">', 1)
        self.assertEqual(re.findall(r'data-rank="(\d+)"', visible), [str(i) for i in range(1, 8)])
        self.assertEqual(re.findall(r'data-rank="(\d+)"', tail), ["8", "9"])

        arms = [{"name": f"arm-{index}"} for index in range(9)]
        experiment = build.experiment_metric_table(
            {"metric": "cost_usd", "kind": "mean", "arms": []}, arms
        )
        self.assertIn("<summary>Show 2 more arms</summary>", experiment)
        visible, tail = experiment.split('<details class="analytics-table-more">', 1)
        self.assertEqual(re.findall(r'data-label="Arm"><span class="value">(.*?)</span>', visible), [f"arm-{i}" for i in range(7)])
        self.assertEqual(re.findall(r'data-label="Arm"><span class="value">(.*?)</span>', tail), ["arm-7", "arm-8"])

    def test_completions_preview_is_newest_first_and_anchor_stays_on_heading(self):
        directory = build.latest_analytics_dir(ROOT)
        metrics = json.loads((directory / "metrics.json").read_text(encoding="utf-8"))
        buckets = metrics["completions"]["buckets"]
        self.assertGreater(len(buckets), analytics_page.TABLE_PREVIEW_ROWS)
        rendered = analytics_page.section_completions(metrics)
        table_start = rendered.index("<caption>Tasks closed per UTC day")
        table_end = rendered.index("</table>", table_start)
        first_table = rendered[table_start:table_end]
        indexes = re.findall(r'data-field="completions\.buckets\.(\d+)\.start"', first_table)
        self.assertEqual(indexes, [str(i) for i in reversed(range(len(buckets)))][:7])
        self.assertTrue(rendered.startswith('<section id="completed" aria-labelledby="completed-title">'))

    def test_disclosure_css_uses_theme_tokens_focus_and_bounded_phone_scrolling(self):
        css = (ROOT / "public" / "assets" / "notes.css").read_text(encoding="utf-8")
        self.assertIn("--link: #2F67D8", css)
        self.assertIn(":root[data-theme=\"dark\"]", css)
        self.assertIn("--link: #8AB3FF", css)
        self.assertRegex(css, r"\.analytics-table-more summary:focus-visible\s*\{[^}]*outline: 2px solid var\(--link\)")
        self.assertIn(".analytics .table { max-width: 100%; overflow-x: auto; overflow-y: hidden; }", css)
        self.assertIn(".analytics section[id] { scroll-margin-top: 80px; }", css)


if __name__ == "__main__":
    unittest.main()
