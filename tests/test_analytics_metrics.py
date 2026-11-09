"""The public metrics page is a pure rendering of data/analytics/*/metrics.json."""

import json
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

import analytics_page

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = (
    re.compile(r"ORB-\d+"),
    re.compile(r"/api/"),
    re.compile(r"\bws_[A-Za-z0-9]+"),
    re.compile(r"task_id"),
    re.compile(r"run_id"),
    re.compile(r"/home/"),
    re.compile(r"model unknown"),
    re.compile(r"crew unknown"),
    re.compile(r"crew unavailable"),
    re.compile(r"\bGET "),
    re.compile(r"fetch\s*\("),
    re.compile(r"XMLHttpRequest"),
    re.compile(r"localhost"),
)


def local_ms(value):
    amount = float(value)
    if amount < 60000:
        return f"{round(amount / 1000)}s"
    minutes = amount / 60000
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = int(minutes // 60)
    rest = round(minutes - hours * 60)
    if rest == 60:
        hours += 1
        rest = 0
    return f"{hours}h {rest:02d}m"


def lookup(obj, path):
    current = obj
    for part in path.split("."):
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


def series_values(metrics, path, unit):
    parts = path.split(".")
    if parts[:2] == ["durations", "buckets"] and len(parts) == 4 and parts[2] in {"all", "low", "medium", "hard"}:
        stat = parts[3]
        values = []
        for bucket in metrics["durations"]["buckets"]:
            cell = bucket.get(parts[2])
            raw = cell.get(stat) if isinstance(cell, dict) else None
            values.append(analytics_page.chart_value(raw, unit))
        return values
    if path == "durations.buckets.other_runs":
        return [float(bucket.get("other_runs") or 0) for bucket in metrics["durations"]["buckets"]]
    if parts[:3] == ["completions", "buckets", "done"] and len(parts) == 4:
        key = parts[3]
        return [float((bucket.get("done") or {}).get(key) or 0) for bucket in metrics["completions"]["buckets"]]
    if parts[:3] == ["defects", "buckets", "lineage"] and len(parts) == 4:
        key = parts[3]
        return [float((bucket.get("lineage") or {}).get(key) or 0) for bucket in metrics["defects"]["buckets"]]
    if parts[:2] == ["tokens", "series"] and parts[3:] == ["points", "mean"]:
        series = metrics["tokens"]["series"][int(parts[2])]
        return [analytics_page.chart_value((point or {}).get("mean"), unit) for point in series["points"]]
    if parts[:2] == ["turns", "series"] and parts[3:] == ["points", "mean_turns"]:
        series = metrics["turns"]["series"][int(parts[2])]
        return [analytics_page.chart_value((point or {}).get("mean_turns"), unit) for point in series["points"]]
    if path == "diff.overall.points.mean.net":
        points = metrics["diff"]["overall"]["points"]
        return [analytics_page.chart_value(((point or {}).get("mean") or {}).get("net"), unit) for point in points]
    if parts[:2] == ["friction", "families"] and parts[3:] == ["points", "count"]:
        family = metrics["friction"]["families"][int(parts[2])]
        return [analytics_page.chart_value((point or {}).get("count"), unit) for point in family["points"]]
    if parts[:2] == ["durations", "actors"] and parts[3] == "trend":
        trend = metrics["durations"]["actors"][int(parts[2])]["trend"]
        return [analytics_page.chart_value(value, unit) for value in trend]
    raise AssertionError(f"unknown series {path}")


def expected_runs(values, y_max, width, height, pad):
    left, top, right, bottom = pad, pad, width - pad, height - pad
    count = len(values)
    runs = []
    current = []

    def finish():
        nonlocal current
        if current:
            runs.append(" ".join(current))
            current = []

    for index, value in enumerate(values):
        if value is None:
            finish()
            continue
        if count <= 1:
            x_pos = (left + right) / 2
        else:
            x_pos = left + (right - left) * index / (count - 1)
        fraction = 0 if not y_max else min(max(float(value) / float(y_max), 0), 1)
        y_pos = bottom - (bottom - top) * fraction
        current.append(f"{x_pos:.2f},{y_pos:.2f}")
    finish()
    return runs


def expected_rects(series_values, y_max, width, height, pad):
    left, top, right, bottom = pad, pad, width - pad, height - pad
    count = len(series_values[0]) if series_values else 0
    if not count or not y_max:
        return [[] for _ in series_values]
    slot = (right - left) / count
    gap = min(2.0, slot * 0.28)
    bar_w = max(slot - gap, 0.4)
    plot_h = bottom - top
    rects = []
    for series_index, series in enumerate(series_values):
        row = []
        for index, value in enumerate(series):
            amount = float(value or 0)
            if amount <= 0:
                continue
            below = sum(float(series_values[earlier][index] or 0) for earlier in range(series_index))
            height_px = plot_h * amount / float(y_max)
            y_pos = bottom - plot_h * (below + amount) / float(y_max)
            x_pos = left + index * slot + (slot - bar_w) / 2
            row.append((f"{x_pos:.2f}", f"{y_pos:.2f}", f"{bar_w:.2f}", f"{height_px:.2f}"))
        rects.append(row)
    return rects


def expected_text(metrics, attrs):
    fmt = attrs["data-format"]
    value = lookup(metrics, attrs["data-field"])
    previous = lookup(metrics, attrs["data-prev"]) if "data-prev" in attrs else None
    base = lookup(metrics, attrs["data-base"]) if "data-base" in attrs else None
    unit = lookup(metrics, attrs["data-unit"]) if "data-unit" in attrs else None
    if fmt == "text":
        return str(value)
    if fmt == "stamp":
        return analytics_page.format_stamp(value)
    if fmt == "day":
        return analytics_page.format_day(value)
    if fmt == "duration":
        return analytics_page.format_ms(value)
    if fmt in {"seconds", "runs", "tasks", "defects", "events", "rejected", "archived", "deliveries", "tokens", "invocations"}:
        return analytics_page.unit_count(value, fmt if fmt != "seconds" else "seconds")
    if fmt == "bytes":
        return analytics_page.unit_count(value, "B")
    if fmt == "usd":
        return analytics_page.format_usd(value)
    if fmt == "lines":
        return analytics_page.format_lines(value)
    if fmt == "turns":
        return analytics_page.format_turns(value)
    if fmt == "percent":
        return analytics_page.format_percent(value)
    if fmt == "share":
        return analytics_page.format_share(value, base)
    if fmt == "ratio":
        return analytics_page.format_ratio(value, base)
    if fmt == "scope":
        return analytics_page.format_scope(value)
    if fmt == "per-done":
        # Derived on the page: the field divided by its base, two decimals.
        return f"{float(value) / float(base):.2f}"
    if fmt == "usd-per":
        if value is None or isinstance(value, bool):
            return "—"
        return f"{float(value):,.2f} USD per done task"
    if fmt == "family-count":
        if unit == "usd":
            return analytics_page.format_usd(value)
        return analytics_page.unit_count(value, unit)
    if fmt.startswith("delta-"):
        return analytics_page.format_delta(value, previous, fmt.split("-", 1)[1])
    raise AssertionError(fmt)


class Node:
    def __init__(self, tag, attrs):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []
        self.text = ""


class Tree(HTMLParser):
    void = {"meta", "link", "img", "br", "hr", "input", "source", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.void:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                return

    def handle_data(self, data):
        self.stack[-1].text += data


def elements(node, pred, found=None):
    found = [] if found is None else found
    if pred(node):
        found.append(node)
    for child in node.children:
        elements(child, pred, found)
    return found


def direct_text(node):
    return node.text


def all_text(node):
    return node.text + "".join(all_text(child) for child in node.children)


class MetricsPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.day, cls.metrics = analytics_page.newest_metrics(ROOT)
        cls.html = analytics_page.render_page(ROOT, cls.metrics, cls.day)
        parser = Tree()
        parser.feed(cls.html)
        cls.tree = parser.root

    def test_outcome_caveat_and_meta_description_match_board_filters(self):
        caveats = elements(
            self.tree,
            lambda node: node.tag == "section" and node.attrs.get("id") == "caveats",
        )
        self.assertEqual(len(caveats), 1)
        caveat_text = all_text(caveats[0])
        self.assertIn("Duration uses succeeded runs.", caveat_text)
        self.assertIn("Tokens and turns use done tasks.", caveat_text)
        # Completions/cost omit a run-outcome query parameter, but their
        # displayed cohorts are still restricted to done tasks; the caveat
        # must not imply they cover all task outcomes.
        self.assertIn(
            "Completions and cost take no run-outcome query filter, but "
            "completions count tasks moved to done and cost covers spend "
            "for tasks that reached done.",
            caveat_text,
        )
        self.assertIn("Other boards take no run-outcome query filter.", caveat_text)
        self.assertNotIn("Other boards have no outcome filter.", caveat_text)

        # The caveat's done-task cohorts match each board's own intro.
        for section_id, phrase in (
            ("completed", "moved to done"),
            ("cost", "for tasks that reached done"),
        ):
            with self.subTest(section=section_id):
                sections = elements(
                    self.tree,
                    lambda node: node.tag == "section"
                    and node.attrs.get("id") == section_id,
                )
                self.assertEqual(len(sections), 1)
                self.assertIn(phrase, all_text(sections[0]))

        expected = (
            "30-day Orbit metrics: duration for succeeded runs; tokens and turns for done tasks; "
            "plus completions, defects, cost, diff size and friction."
        )
        descriptions = elements(
            self.tree,
            lambda node: node.tag == "meta"
            and node.attrs.get("name") == "description",
        )
        open_graph_descriptions = elements(
            self.tree,
            lambda node: node.tag == "meta"
            and node.attrs.get("property") == "og:description",
        )
        self.assertEqual([node.attrs["content"] for node in descriptions], [expected])
        self.assertEqual([node.attrs["content"] for node in open_graph_descriptions], [expected])

    def test_format_matches_the_dashboard_duration_rule(self):
        # Fixed fixtures cover the sub-minute, minute and hour branches
        # without depending on whatever the newest live snapshot holds.
        for value, expected in ((45000, "45s"), (1200000, "20.0m"), (3660000, "1h 01m")):
            self.assertEqual(analytics_page.format_ms(value), expected)
            self.assertEqual(local_ms(value), expected)
        average = self.metrics["durations"]["current"]["all"]["avg"]
        self.assertEqual(analytics_page.format_ms(average), local_ms(average))
        self.assertIn(f">{analytics_page.format_ms(average)}<", self.html)

    def test_format_stamp_and_day_use_fixed_inputs(self):
        # Fixed inputs pin the formatting so integration tests can derive
        # expectations from whichever snapshot/window is selected.
        for value, expected in (
            ("2026-10-09T00:00:00+00:00", "9 Oct 2026, 00:00 UTC"),
            ("2026-10-10T00:00:00+00:00", "10 Oct 2026, 00:00 UTC"),
            ("2026-11-09T17:22:30+00:00", "9 Nov 2026, 17:22 UTC"),
        ):
            self.assertEqual(analytics_page.format_stamp(value), expected)
        self.assertEqual(analytics_page.format_day("2026-11-09T00:00:00+00:00"), "9 Nov")

    def test_newest_metrics_selects_the_later_isolated_snapshot(self):
        fixtures = (
            ("2026-11-08", "2026-10-09T00:00:00+00:00", "2026-11-08T00:00:00+00:00"),
            ("2026-11-09", "2026-10-10T00:00:00+00:00", "2026-11-09T00:00:00+00:00"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for day, since, until in fixtures:
                directory = root / "data" / "analytics" / day
                directory.mkdir(parents=True)
                payload = {
                    "schema_version": 1,
                    "durations": {"window": {"since": since, "until": until}},
                }
                (directory / "metrics.json").write_text(json.dumps(payload), encoding="utf-8")
            day, metrics = analytics_page.newest_metrics(root)
        self.assertEqual(day, "2026-11-09")
        self.assertEqual(metrics["durations"]["window"]["since"], "2026-10-10T00:00:00+00:00")
        self.assertEqual(
            analytics_page.format_stamp(metrics["durations"]["window"]["since"]),
            "10 Oct 2026, 00:00 UTC",
        )

    def test_windowed_sections_show_utc_bounds_and_outcomes_show_scope(self):
        # One window statement up top; a board repeats a window only when its own differs.
        page_window = self.metrics["durations"]["window"]
        heroes = elements(
            self.tree,
            lambda node: node.tag == "p" and "window-statement" in node.attrs.get("class", "").split(),
        )
        self.assertEqual(len(heroes), 1)
        for bound in ("since", "until"):
            stamps = elements(
                heroes[0],
                lambda node: node.tag == "time" and node.attrs.get("data-field") == f"durations.window.{bound}",
            )
            self.assertEqual([node.attrs["datetime"] for node in stamps], [page_window[bound]])
        windowed_sections = {
            "duration": "durations",
            "completed": "completions",
            "defects": "defects",
            "tokens": "tokens",
            "cost": "friction",
            "diff": "diff",
            "friction": "friction",
            "turns": "turns",
        }
        for section_id, metrics_path in windowed_sections.items():
            with self.subTest(section=section_id):
                section_nodes = elements(
                    self.tree,
                    lambda node: node.tag == "section" and node.attrs.get("id") == section_id,
                )
                self.assertEqual(len(section_nodes), 1)
                section_node = section_nodes[0]
                window = lookup(self.metrics, f"{metrics_path}.window")
                same = analytics_page.same_window(window, page_window)
                for bound in ("since", "until"):
                    timestamps = elements(
                        section_node,
                        lambda node: node.tag == "time"
                        and node.attrs.get("data-field") == f"{metrics_path}.window.{bound}",
                    )
                    if same:
                        # Printed the same as the page window: not repeated on the board.
                        self.assertEqual(timestamps, [])
                        self.assertEqual(
                            analytics_page.format_stamp(window[bound]),
                            analytics_page.format_stamp(page_window[bound]),
                        )
                    else:
                        self.assertEqual(len(timestamps), 1)
                        self.assertEqual(timestamps[0].attrs["datetime"], window[bound])

        outcome_sections = elements(
            self.tree,
            lambda node: node.tag == "section" and node.attrs.get("id") == "outcomes",
        )
        self.assertEqual(len(outcome_sections), 1)
        outcome_section = outcome_sections[0]
        scope_lines = elements(
            outcome_section,
            lambda node: node.tag == "p" and "window" in node.attrs.get("class", "").split(),
        )
        self.assertEqual(len(scope_lines), 1)
        scope_values = elements(
            scope_lines[0],
            lambda node: node.tag == "span"
            and node.attrs.get("data-field") == "completion_by_complexity.scope",
        )
        mix = self.metrics["completion_by_complexity"]
        self.assertEqual(
            [node.text for node in scope_values],
            [analytics_page.format_scope(mix.get("scope"))],
        )
        self.assertTrue(scope_lines[0].text.strip().startswith("Scope"))
        outcome_bounds = elements(
            outcome_section,
            lambda node: node.tag == "time"
            and node.attrs.get("data-field", "").endswith((".since", ".until")),
        )
        self.assertEqual(outcome_bounds, [])

        window = self.metrics["durations"]["window"]
        self.assertIn(analytics_page.format_stamp(window["since"]), self.html)
        self.assertIn(f">{window['key']}<", self.html)
        self.assertEqual(self.metrics["outcome"], "succeeded")
        self.assertEqual(self.metrics["durations"]["outcome"], "succeeded")
        self.assertIn(">succeeded<", self.html)

    def test_every_marked_figure_matches_a_metrics_field(self):
        marked = elements(self.tree, lambda node: "data-format" in node.attrs)
        self.assertGreater(len(marked), 200)
        for node in marked:
            expected = expected_text(self.metrics, node.attrs)
            self.assertEqual(direct_text(node).strip(), expected, node.attrs.get("data-field"))
            if node.attrs["data-format"] in {"stamp", "day"}:
                self.assertEqual(node.attrs["datetime"], lookup(self.metrics, node.attrs["data-field"]))

    def test_line_and_stack_charts_trace_to_series(self):
        plots = elements(self.tree, lambda node: node.tag == "svg" and "plot" in node.attrs.get("class", "").split())
        self.assertGreaterEqual(len(plots), 6)
        for svg in plots:
            width = float(svg.attrs["data-width"])
            height = float(svg.attrs["data-height"])
            pad = float(svg.attrs["data-pad"])
            y_max = float(svg.attrs["data-ymax"])
            unit = svg.attrs["data-unit"]
            if svg.attrs.get("data-chart") == "stack":
                groups = [child for child in svg.children if child.tag == "g"]
                loaded = []
                for group in groups:
                    rects = [child for child in group.children if child.tag == "rect"]
                    if not rects:
                        loaded.append([])
                        continue
                    loaded.append(series_values(self.metrics, rects[0].attrs["data-series"], unit))
                # A series that is entirely zero still occupies a group with no rects.
                # Recover its path from a sibling is unnecessary: empty groups are all zeros
                # only when the renderer emitted the group. Rebuild from rect paths plus
                # zeros for empty groups by using the field stamped on a non-empty rect,
                # and for an empty group accept an all-zero expected row of the same length.
                length = max(len(row) for row in loaded if row)
                normalized = []
                for row in loaded:
                    normalized.append(row if row else [0.0] * length)
                # Empty groups cannot recover the field, so compare geometry only for
                # groups that have rects, against the loaded values.
                got = []
                expect = expected_rects(normalized, y_max, width, height, pad)
                for group, expected_row, loaded_row in zip(groups, expect, normalized):
                    rects = [child for child in group.children if child.tag == "rect"]
                    actual = [(rect.attrs["x"], rect.attrs["y"], rect.attrs["width"], rect.attrs["height"]) for rect in rects]
                    if loaded_row:
                        self.assertEqual(actual, expected_row)
                    else:
                        self.assertEqual(actual, [])
                    got.append(actual)
                self.assertTrue(any(row for row in got))
                continue
            groups = [child for child in svg.children if child.tag == "g" and "data-series" in child.attrs]
            self.assertGreaterEqual(len(groups), 1)
            peak = 0.0
            saw = False
            for group in groups:
                values = series_values(self.metrics, group.attrs["data-series"], unit)
                for value in values:
                    if value is not None:
                        peak = max(peak, value)
                        saw = True
                polylines = [child.attrs["points"] for child in group.children if child.tag == "polyline"]
                self.assertEqual(polylines, expected_runs(values, y_max, width, height, pad), group.attrs["data-series"])
            self.assertTrue(saw)
            self.assertEqual(y_max, analytics_page.nice_ceiling(peak))

    def test_sparklines_and_share_bars_trace_to_fields(self):
        sparks = elements(self.tree, lambda node: node.tag == "svg" and node.attrs.get("class") == "spark")
        self.assertGreater(len(sparks), 5)
        for svg in sparks:
            values = series_values(self.metrics, svg.attrs["data-series"], svg.attrs["data-unit"])
            y_max = float(svg.attrs["data-ymax"])
            polylines = [child.attrs["points"] for child in svg.children if child.tag == "polyline"]
            self.assertEqual(polylines, expected_runs(
                values, y_max, float(svg.attrs["data-width"]), float(svg.attrs["data-height"]), float(svg.attrs["data-pad"]),
            ))
        bars = elements(self.tree, lambda node: node.tag == "rect" and "data-field" in node.attrs and "data-series" not in node.attrs)
        self.assertGreater(len(bars), 5)
        for rect in bars:
            value = float(lookup(self.metrics, rect.attrs["data-field"]) or 0)
            parent = self._parent(rect)
            plot_w = float(parent.attrs["data-plot-w"])
            if "data-total" in rect.attrs:
                total = float(lookup(self.metrics, rect.attrs["data-total"]) or 0)
                scale = total
            else:
                scale = float(parent.attrs["data-ymax"])
            expect = 0 if not scale else max(0.0, min(plot_w, plot_w * value / scale))
            self.assertAlmostEqual(float(rect.attrs["width"]), expect, places=2)

    def test_no_unmarked_digits_fetches_or_forbidden_identifiers(self):
        for pattern in FORBIDDEN:
            self.assertIsNone(pattern.search(self.html), pattern.pattern)
        for board in ("durations", "completions", "defects", "tokens", "turns", "diff", "friction"):
            source = self.metrics[board].get("source")
            if source:
                self.assertNotIn(source, self.html)
        scripts = re.findall(r'<script[^>]*src="([^"]+)"', self.html)
        self.assertTrue(scripts)
        self.assertTrue(all("theme" in src or "analytics.js" in src for src in scripts))
        script = (ROOT / "public" / "assets" / "analytics.js").read_text(encoding="utf-8")
        for pattern in (r"fetch\s*\(", "XMLHttpRequest", "/api/", "localhost"):
            self.assertIsNone(re.search(pattern, script), pattern)
        problems = []

        def walk(node):
            classes = node.attrs.get("class", "").split()
            skip_text = (
                node.tag in {"script", "style", "svg", "footer", "time", "summary"}
                or "data-format" in node.attrs
                or "data-axis" in node.attrs
                or "label" in classes
            )
            if not skip_text and re.search(r"\d", node.text):
                problems.append(node.text.strip()[:80])
            if node.tag in {"script", "style", "svg", "footer"} or "data-format" in node.attrs:
                return
            for child in node.children:
                walk(child)

        walk(self.tree)
        self.assertEqual(problems, [])

    def test_build_writes_the_newest_snapshot_page(self):
        analytics_page.build(ROOT)
        page = ROOT / "public" / "analytics" / "metrics" / "index.html"
        self.assertTrue(page.is_file())
        text = page.read_text(encoding="utf-8")
        self.assertIn(self.metrics["durations"]["window"]["since"], text)
        self.assertIn('href="https://constellation-works.com/analytics/metrics/"', text)
        expected_day = max(
            path.name
            for path in (ROOT / "data" / "analytics").iterdir()
            if path.is_dir()
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.name)
            and (path / "metrics.json").is_file()
        )
        self.assertEqual(self.day, expected_day)

    def test_every_table_cell_names_its_column_for_the_stacked_phone_layout(self):
        # At <=560px the header row is hidden and each row stacks, so a cell without
        # data-label would show a bare figure.
        tables = elements(self.tree, lambda node: node.tag == "table")
        self.assertGreaterEqual(len(tables), 10)
        for table in tables:
            head = elements(table, lambda node: node.tag == "th" and node.attrs.get("scope") == "col")
            headers = [all_text(cell).strip() for cell in head]
            for row in elements(table, lambda node: node.tag == "tr"):
                cells = [child for child in row.children if child.tag in {"td", "th"}]
                if any(cell.attrs.get("scope") == "col" for cell in cells):
                    continue
                self.assertEqual(len(cells), len(headers))
                for cell, header in zip(cells, headers):
                    self.assertEqual(cell.attrs.get("data-label"), header)

    def test_stylesheet_wraps_long_table_labels_on_a_phone(self):
        # The "other" crew row lists every pooled crew name in its row header. In the
        # stacked layout that header must wrap inside the column (it overflowed to 590px
        # at 375px when it did not), and the figures beside it must wrap too.
        css = (ROOT / "public" / "assets" / "analytics.css").read_text(encoding="utf-8")
        phone = [
            block
            for block in re.findall(r"@media \(max-width: 560px\) \{(.*?)\n\}", css, re.S)
            if "table" in block or " th" in block or " td" in block
        ]
        self.assertTrue(phone, "analytics.css needs a <=560px table rule")
        rules = "\n".join(phone)
        wrap = re.search(r"\.analytics th,\s*\.analytics td \{[^}]*overflow-wrap: anywhere", rules)
        self.assertIsNotNone(wrap, "table cells must use overflow-wrap: anywhere on a phone")
        row_header = re.search(r'\.analytics tbody th\[scope="row"\] \{[^}]*display: block', rules)
        self.assertIsNotNone(row_header, "row headers must stop being a nowrap flex row on a phone")
        self.assertIn("min-width: 0", rules)

    def test_boards_are_grouped_and_render_stacked_without_javascript(self):
        expected = {
            "speed": ["duration", "turns"],
            "throughput": ["completed", "outcomes"],
            "quality": ["defects", "friction"],
            "spend": ["cost", "tokens", "diff"],
        }
        groups = elements(self.tree, lambda node: node.tag == "section" and "data-group" in node.attrs)
        self.assertEqual([node.attrs["id"] for node in groups], list(expected))
        for group in groups:
            boards = elements(group, lambda node: node.tag == "section" and "metric-board" in node.attrs.get("class", ""))
            self.assertEqual([node.attrs["id"] for node in boards], expected[group.attrs["id"]])
            self.assertNotIn("hidden", group.attrs)
        # The group links are plain anchors; only the JS-only "All" tab ships hidden.
        nav = elements(self.tree, lambda node: node.tag == "nav" and "group-nav" in node.attrs.get("class", ""))
        self.assertEqual(len(nav), 1)
        links = elements(nav[0], lambda node: node.tag == "a")
        self.assertEqual([link.attrs["href"] for link in links], ["#speed", "#throughput", "#quality", "#spend", "#metrics-all"])
        hidden = elements(self.tree, lambda node: "hidden" in node.attrs)
        self.assertEqual([node.tag for node in hidden], ["button", "li"])

    def test_glance_tiles_link_to_boards_and_follow_metric_direction(self):
        tiles = elements(self.tree, lambda node: node.tag == "a" and "tile" in node.attrs.get("class", "").split())
        self.assertGreaterEqual(len(tiles), 8)
        board_ids = {node.attrs["id"] for node in elements(self.tree, lambda node: "metric-board" in node.attrs.get("class", ""))}
        for tile in tiles:
            self.assertIn(tile.attrs["href"][1:], board_ids)
        deltas = {}
        for tile in tiles:
            label = all_text(elements(tile, lambda node: "tile-label" in node.attrs.get("class", ""))[0])
            found = elements(tile, lambda node: "delta" in node.attrs.get("class", "").split())
            deltas[label] = found[0].attrs["class"].split()[-1] if found else None
        cur, prev = self.metrics["durations"]["current"]["all"]["avg"], self.metrics["durations"]["previous"]["all"]["avg"]
        self.assertEqual(deltas["Duration"], analytics_page.delta_class(cur, prev, "duration"))
        cur, prev = self.metrics["defects"]["current"]["total"], self.metrics["defects"]["previous"]["total"]
        self.assertEqual(deltas["Defects"], analytics_page.delta_class(cur, prev, "worse"))
        done = self.metrics["completions"]["current"]["done"]["total"]
        prev_done = self.metrics["completions"]["previous"]["done"]["total"]
        self.assertEqual(
            deltas["Defects per done task *"],
            analytics_page.delta_class(cur / done, prev / prev_done, "worse"),
        )
        # The derived tile and its footnote say how the rate is computed.
        self.assertIn("* derived on this page", self.html)
        caveats = all_text(elements(self.tree, lambda node: node.attrs.get("id") == "caveats")[0])
        self.assertIn("* Derived on this page: defects per done task is defects filed in the window divided by tasks moved to done", caveats)

    def test_coverage_and_thin_sample_warnings_come_from_the_snapshot(self):
        def warnings(section_id):
            section = elements(self.tree, lambda node: node.tag == "section" and node.attrs.get("id") == section_id)[0]
            return elements(section, lambda node: node.tag == "p" and "warn" in node.attrs.get("class", "").split())

        coverage = self.metrics["turns"]["coverage"]
        turns = warnings("turns")
        self.assertEqual(len(turns), 1 if coverage["measured_rate"] < analytics_page.COVERAGE_WARN_RATE else 0)
        if turns:
            fields = [node.attrs.get("data-field") for node in elements(turns[0], lambda node: "data-field" in node.attrs)]
            self.assertEqual(fields, ["turns.coverage.measured", "turns.coverage.tasks", "turns.coverage.measured_rate"])
        thin = [
            key for key in ("low", "medium", "hard", "xhard")
            if isinstance(self.metrics["durations"]["current"].get(key), dict)
            and 0 < self.metrics["durations"]["current"][key]["n"] < analytics_page.THIN_TIER_RUNS
        ]
        duration = warnings("duration")
        self.assertEqual(len(duration), 1 if thin else 0)
        if thin:
            fields = [node.attrs.get("data-field") for node in elements(duration[0], lambda node: "data-field" in node.attrs)]
            self.assertEqual(fields, [f"durations.current.{key}.n" for key in thin])

        # The same renderer stays quiet when coverage is full.
        import copy
        full = copy.deepcopy(self.metrics)
        full["turns"]["coverage"]["measured_rate"] = 0.9
        self.assertNotIn('class="warn"', analytics_page.section_turns(full))

    def test_outcome_board_is_labelled_all_time_and_daily_tables_collapse(self):
        outcomes = elements(self.tree, lambda node: node.tag == "section" and node.attrs.get("id") == "outcomes")[0]
        self.assertIn("All time, not the window above", all_text(outcomes))
        for caption in ("Average duration and runs per UTC day", "Tasks closed per UTC day", "Defects per UTC day"):
            start = self.html.index(f"<caption>{caption}")
            opened = self.html.rfind('<details class="more">', 0, start)
            closed = self.html.rfind("</details>", 0, start)
            self.assertGreater(opened, closed, caption)

    def _parent(self, target):
        found = []

        def walk(node):
            for child in node.children:
                if child is target:
                    found.append(node)
                walk(child)

        walk(self.tree)
        self.assertEqual(len(found), 1)
        return found[0]


if __name__ == "__main__":
    unittest.main()
