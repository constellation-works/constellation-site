"""Formatting, chart primitives, tables and board chrome.

Moved unchanged from analytics_page.py.
"""

import datetime
import hashlib
import re

from .common import (
    CHART_W,
    CHART_H,
    CHART_PAD,
    TABLE_PREVIEW_ROWS,
    SCOPE_LABEL,
    e,
)

def asset(root, name):
    digest = hashlib.sha256((root / "public" / "assets" / name).read_bytes()).hexdigest()
    return f"/assets/{name}?v={digest[:10]}"


def parse_time(value):
    text = str(value).replace("Z", "+00:00")
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    parsed = datetime.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def format_stamp(value):
    parsed = parse_time(value)
    return f"{parsed.day} {parsed.strftime('%b %Y, %H:%M')} UTC"


def format_day(value):
    parsed = parse_time(value)
    return f"{parsed.day} {parsed.strftime('%b')}"


def format_ms(value):
    if value is None or isinstance(value, bool):
        return "—"
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


def format_int(value):
    if value is None or isinstance(value, bool):
        return "—"
    return f"{int(round(float(value))):,}"


def format_usd(value):
    if value is None or isinstance(value, bool):
        return "—"
    return f"{float(value):,.2f} USD"


def format_lines(value):
    if value is None or isinstance(value, bool):
        return "—"
    amount = float(value)
    if abs(amount - round(amount)) < 1e-9:
        return f"{int(round(amount)):,} lines"
    return f"{amount:,.1f} lines"


def format_turns(value):
    if value is None or isinstance(value, bool):
        return "—"
    return f"{float(value):,.1f} turns"


def format_percent(value):
    if value is None or isinstance(value, bool):
        return "—"
    return f"{float(value) * 100:.1f}%"


def format_ratio(part, total):
    if part is None or isinstance(part, bool) or not total:
        return "—"
    return f"{float(part) / float(total) * 100:.1f}%"


def format_share(part, total):
    if part is None or isinstance(part, bool) or not total:
        return "—"
    return f"{round(float(part) / float(total) * 100)}% of done"


def per_done(part, total):
    """Derived on this page: a count divided by the tasks done in the same window."""
    if part is None or isinstance(part, bool) or not total or isinstance(total, bool):
        return None
    return float(part) / float(total)


def format_per_done(part, total):
    value = per_done(part, total)
    return "—" if value is None else f"{value:.2f}"


def format_scope(value):
    return SCOPE_LABEL.get(value, str(value))


def format_delta(current, previous, mode):
    if current is None or isinstance(current, bool):
        return "—"
    if previous is None or isinstance(previous, bool) or float(previous) == 0:
        return "new"
    ratio = (float(current) - float(previous)) / float(previous) * 100
    magnitude = abs(ratio)
    number = f"{magnitude:.0f}" if magnitude >= 10 else f"{magnitude:.1f}"
    arrow = "▲" if ratio >= 0 else "▼"
    if mode == "duration":
        word = "slower" if ratio >= 0 else "faster"
    elif mode.startswith("rate-"):
        word = "higher" if ratio >= 0 else "lower"
    else:
        word = "more" if ratio >= 0 else "fewer"
    return f"{arrow} {number}% {word}"


def delta_class(current, previous, mode):
    if current is None or previous is None or isinstance(current, bool) or isinstance(previous, bool):
        return "flat"
    if float(previous) == 0:
        return "flat"
    ratio = (float(current) - float(previous)) / float(previous) * 100
    worse_when_up = mode in ("duration", "worse", "rate-worse")
    if abs(ratio) <= 5:
        return "flat"
    up_is_bad = ratio > 0 if worse_when_up else ratio < 0
    return "bad" if up_is_bad else "good"


def unit_count(value, unit):
    rendered = format_int(value)
    if rendered == "—":
        return rendered
    return f"{rendered} {unit}"


def fig(text, fmt, field, cls=None, **attrs):
    class_attr = f' class="{e(cls)}"' if cls else ""
    extra = "".join(
        f' data-{key.replace("_", "-")}="{e(val)}"' for key, val in attrs.items() if val is not None
    )
    return f'<span{class_attr} data-format="{e(fmt)}" data-field="{e(field)}"{extra}>{e(text)}</span>'


def text_fig(value, field):
    return fig(str(value), "text", field)


def delta_fig(current, previous, mode, field, prev_field):
    return fig(
        format_delta(current, previous, mode),
        f"delta-{mode}",
        field,
        cls=f"delta {delta_class(current, previous, mode)}",
        prev=prev_field,
    )


def stamp(value, field):
    if not value:
        return ""
    return (
        f'<time datetime="{e(value)}" data-format="stamp" data-field="{e(field)}">'
        f"{e(format_stamp(value))}</time>"
    )


def day_cell(value, field):
    return (
        f'<time datetime="{e(value)}" data-format="day" data-field="{e(field)}">'
        f"{e(format_day(value))}</time>"
    )


def window_line(window, prefix):
    if not isinstance(window, dict) or not window.get("since") or not window.get("until"):
        return ""
    parts = ["<p class=\"window\">UTC window ", stamp(window["since"], f"{prefix}.since"),
             " – ", stamp(window["until"], f"{prefix}.until")]
    if window.get("key"):
        parts.append(" · ")
        parts.append(text_fig(window["key"], f"{prefix}.key"))
    if window.get("bucket_seconds") is not None:
        parts.append(" · buckets ")
        parts.append(fig(unit_count(window["bucket_seconds"], "seconds"), "seconds", f"{prefix}.bucket_seconds"))
    parts.append("</p>")
    return "".join(parts)


def nice_ceiling(value):
    if value is None or value <= 0:
        return 1.0
    padded = float(value) * 1.05
    exponent = math_floor_log10(padded)
    base = 10 ** exponent
    for factor in (1, 2, 2.5, 5, 10):
        ceiling = factor * base
        if ceiling + 1e-9 >= padded:
            return float(ceiling)
    return float(10 * base)


def math_floor_log10(value):
    import math
    return math.floor(math.log10(value))


def axis_label(value, unit):
    if unit == "minutes":
        return axis_minutes(value)
    if unit == "percent":
        return f"{value:g}%"
    if unit == "usd":
        return f"{value:,.0f} USD" if value >= 100 else f"{value:,.2f} USD"
    if unit == "tokens":
        return compact(value)
    if value == 0:
        return "0"
    return format_int(value)


def axis_minutes(minutes):
    if minutes <= 0:
        return "0"
    if minutes < 60:
        return f"{minutes:g}m"
    if abs(minutes % 60) < 1e-6:
        return f"{int(round(minutes / 60))}h"
    hours = int(minutes // 60)
    rest = minutes - hours * 60
    if abs(rest - round(rest)) < 1e-6:
        return f"{hours}h {int(round(rest)):02d}m"
    return f"{hours}h {rest:.0f}m"


def compact(value):
    amount = float(value)
    sign = "-" if amount < 0 else ""
    absolute = abs(amount)
    if absolute >= 1e9:
        return f"{sign}{absolute / 1e9:.1f}B"
    if absolute >= 1e6:
        return f"{sign}{absolute / 1e6:.1f}M"
    if absolute >= 1e3:
        return f"{sign}{absolute / 1e3:.1f}k"
    return f"{sign}{absolute:g}"


def chart_value(raw, unit):
    if raw is None or isinstance(raw, bool):
        return None
    if unit == "minutes":
        return float(raw) / 60000
    if unit == "percent":
        return float(raw) * 100
    return float(raw)


def plot_edges(width, height, pad):
    return pad, pad, width - pad, height - pad


def line_runs(values, y_max, width=CHART_W, height=CHART_H, pad=CHART_PAD):
    """Contiguous point strings. None breaks the line. Coordinates are chart units."""
    left, top, right, bottom = plot_edges(width, height, pad)
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


def stack_rects(series_values, y_max, width=CHART_W, height=CHART_H, pad=CHART_PAD):
    """Positive rectangles per series, bottom to top. series_values align by bucket."""
    left, top, right, bottom = plot_edges(width, height, pad)
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


def bar_width(value, y_max, plot_w):
    if not y_max or value is None:
        return 0.0
    return max(0.0, min(float(plot_w), float(plot_w) * float(value) / float(y_max)))


def svg_open(attrs):
    rendered = " ".join(f'{name}="{e(value)}"' for name, value in attrs.items())
    return f"<svg {rendered}>"


def grid_lines(width, height, pad):
    left, top, right, bottom = plot_edges(width, height, pad)
    lines = []
    for fraction in (0, 0.5, 1):
        y_pos = bottom - (bottom - top) * fraction
        lines.append(
            f'<line class="grid" x1="{left:.2f}" y1="{y_pos:.2f}" x2="{right:.2f}" y2="{y_pos:.2f}"></line>'
        )
    return "".join(lines)


def chart_frame(unit, y_max, svg, first_day, last_day, first_field, last_field):
    labels = (
        ("max", axis_label(y_max, unit)),
        ("mid", axis_label(y_max / 2, unit)),
        ("zero", axis_label(0, unit)),
    )
    axis = "".join(f'<span data-axis="{name}">{e(text)}</span>' for name, text in labels)
    days = ""
    if first_day and last_day:
        days = (
            f'<div class="x-axis">{day_cell(first_day, first_field)}'
            f"{day_cell(last_day, last_field)}</div>"
        )
    return f'<div class="chart"><div class="y-axis" aria-hidden="true">{axis}</div>{svg}</div>{days}'


def line_chart(series, unit, aria, first_day=None, last_day=None, first_field=None, last_field=None):
    """series items: cls, field, values (already in chart units)."""
    peak = 0.0
    for item in series:
        for value in item["values"]:
            if value is not None:
                peak = max(peak, value)
    y_max = nice_ceiling(peak)
    groups = []
    for item in series:
        polylines = "".join(
            f'<polyline class="line {e(item["cls"])}" points="{points}"></polyline>'
            for points in line_runs(item["values"], y_max)
        )
        groups.append(f'<g data-series="{e(item["field"])}">{polylines}</g>')
    svg = svg_open({
        "viewBox": f"0 0 {CHART_W} {CHART_H}",
        "class": "plot",
        "role": "img",
        "aria-label": aria,
        "data-unit": unit,
        "data-ymax": f"{y_max:g}",
        "data-width": str(CHART_W),
        "data-height": str(CHART_H),
        "data-pad": str(CHART_PAD),
    }) + grid_lines(CHART_W, CHART_H, CHART_PAD) + "".join(groups) + "</svg>"
    return chart_frame(unit, y_max, svg, first_day, last_day, first_field, last_field)


def stack_chart(series, unit, aria, first_day=None, last_day=None, first_field=None, last_field=None):
    """series items: cls, field, values (numbers; 0 is an empty slot)."""
    if not series:
        return ""
    totals = [
        sum(float(item["values"][index] or 0) for item in series)
        for index in range(len(series[0]["values"]))
    ]
    y_max = nice_ceiling(max(totals) if totals else 0)
    geometry = stack_rects([item["values"] for item in series], y_max)
    groups = []
    for item, rects in zip(series, geometry):
        body = "".join(
            f'<rect class="bar {e(item["cls"])}" data-series="{e(item["field"])}" '
            f'x="{x}" y="{y}" width="{w}" height="{h}"></rect>'
            for x, y, w, h in rects
        )
        groups.append(f"<g>{body}</g>")
    svg = svg_open({
        "viewBox": f"0 0 {CHART_W} {CHART_H}",
        "class": "plot",
        "role": "img",
        "aria-label": aria,
        "data-unit": unit,
        "data-ymax": f"{y_max:g}",
        "data-width": str(CHART_W),
        "data-height": str(CHART_H),
        "data-pad": str(CHART_PAD),
        "data-chart": "stack",
    }) + grid_lines(CHART_W, CHART_H, CHART_PAD) + "".join(groups) + "</svg>"
    return chart_frame(unit, y_max, svg, first_day, last_day, first_field, last_field)


def legend(items):
    rows = []
    for cls, label, kind in items:
        shape = " bar" if kind == "bar" else ""
        rows.append(f'<li><i class="{e(cls)}{shape}"></i>{e(label)}</li>')
    return f'<ul class="legend">{"".join(rows)}</ul>'


def sparkline(values_ms, field):
    values = [chart_value(item, "minutes") for item in values_ms]
    if not any(value is not None for value in values):
        return "—"
    width, height, pad = 88, 28, 2
    peak = max(value for value in values if value is not None)
    y_max = nice_ceiling(peak)
    polylines = "".join(
        f'<polyline class="line s-all" points="{points}"></polyline>'
        for points in line_runs(values, y_max, width, height, pad)
    )
    return svg_open({
        "viewBox": f"0 0 {width} {height}",
        "class": "spark",
        "role": "img",
        "aria-label": "Average duration by day",
        "data-unit": "minutes",
        "data-ymax": f"{y_max:g}",
        "data-width": str(width),
        "data-height": str(height),
        "data-pad": str(pad),
        "data-series": field,
    }) + polylines + "</svg>"


CELL_OPEN = re.compile(r"<t[dh]\b[^>]*>")


def label_cells(row_html, headers):
    """Tag each cell of a row with its column header, so the phone layout (which hides
    the header row and stacks each row) can still name every figure."""
    position = iter(range(len(headers)))

    def tag(match):
        column = next(position, None)
        if column is None:
            return match.group(0)
        return match.group(0)[:-1] + f' data-label="{e(re.sub(r"<[^>]*>", "", headers[column]))}">'

    return CELL_OPEN.sub(tag, row_html)


def with_row_disclosure(rows, render_table, more_label="rows"):
    """Render a table once when short, or split its rows behind a native disclosure."""
    rows = list(rows)
    if len(rows) <= TABLE_PREVIEW_ROWS:
        return render_table(rows, False)

    hidden_count = len(rows) - TABLE_PREVIEW_ROWS
    return (
        render_table(rows[:TABLE_PREVIEW_ROWS], False)
        + '<details class="analytics-table-more">'
        + f'<summary>Show {hidden_count} more {e(more_label)}</summary>'
        + render_table(rows[TABLE_PREVIEW_ROWS:], True)
        + '</details>'
    )


def table(caption, headers, rows, more_label="rows", preview=True):
    head = "".join(f'<th scope="col">{header}</th>' for header in headers)
    rendered_rows = [
        "<tr>" + label_cells("".join(row_cells), headers) + "</tr>"
        for row_cells in rows
    ]

    def render_table(part, overflow):
        if overflow:
            cap = f'<caption class="sr-only">Additional {e(more_label)}</caption>'
        else:
            cap = f"<caption>{caption}</caption>" if caption else ""
        body = "".join(part)
        return f'<div class="table"><table>{cap}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'

    if not preview:
        return render_table(rendered_rows, False)
    return with_row_disclosure(rendered_rows, render_table, more_label)


def score_card(label, value_html, detail_html=""):
    detail = f'<p class="detail">{detail_html}</p>' if detail_html else ""
    return f'<article class="score"><h4>{e(label)}</h4>{value_html}{detail}</article>'


def cards(html_cards):
    return f'<div class="scores">{"".join(html_cards)}</div>'


def section(anchor, title, intro, body, badge=""):
    return (
        f'<section class="metric-board" id="{e(anchor)}" aria-labelledby="{e(anchor)}-title">'
        f'<div class="board-head"><h3 id="{e(anchor)}-title">{e(title)}</h3>{badge}</div>'
        f'<p class="lede">{intro}</p>{body}</section>'
    )


def more(summary, inner):
    """A native disclosure for secondary detail (daily tables, per-model rows)."""
    if not inner:
        return ""
    return f'<details class="more"><summary>{e(summary)}</summary>{inner}</details>'


def warn(title, body_html):
    return f'<p class="warn"><strong>{e(title)}</strong> <span>{body_html}</span></p>'


def same_window(window, page_window):
    """True when a board's window prints the same as the page window (minute precision)."""
    if not isinstance(window, dict) or not isinstance(page_window, dict):
        return False
    try:
        return (
            window.get("key") == page_window.get("key")
            and format_stamp(window["since"]) == format_stamp(page_window["since"])
            and format_stamp(window["until"]) == format_stamp(page_window["until"])
        )
    except (KeyError, TypeError, ValueError):
        return False


def board_window(window, prefix, metrics):
    """A board prints its own window only when it differs from the page window up top."""
    page_window = (metrics.get("durations") or {}).get("window") or {}
    if same_window(window, page_window):
        return ""
    return window_line(window, prefix)


def bucket_stat(buckets, key, stat, unit):
    values = []
    for bucket in buckets:
        cell = bucket.get(key)
        raw = cell.get(stat) if isinstance(cell, dict) else None
        values.append(chart_value(raw, unit))
    return values
