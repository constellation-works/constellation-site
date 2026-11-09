#!/usr/bin/env python3
"""Render /analytics/metrics/ from the newest committed analytics snapshot.

The page is static HTML. Charts are inline SVG computed here. Nothing in the
output calls an Orbit host. Every measured figure is a span with data-format
and data-field so a test can recompute it from metrics.json.

build.py calls build() after the notes build. public/analytics/ is generated.
"""

import datetime
import hashlib
import html
import json
import pathlib
import re
import shutil
import sys

DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LOW_ACTOR_SAMPLE = 5
CHART_W = 640
CHART_H = 168
CHART_PAD = 8
TABLE_PREVIEW_ROWS = 7

TIER_LABEL = {
    "all": "All",
    "low": "Low",
    "medium": "Medium",
    "hard": "Hard",
    "xhard": "Extra hard",
    "unset": "Unset",
    "other": "Other",
}
DURATION_LINES = ("all", "low", "medium", "hard")
VOLUME_STACK = (("low", "s-low"), ("medium", "s-medium"), ("hard", "s-hard"), ("other_runs", "s-other"))
DONE_STACK = (("low", "s-low"), ("medium", "s-medium"), ("hard", "s-hard"), ("other", "s-other"))
LINEAGE = (
    ("fix_for_fix", "Fix-for-a-fix", "s-fix"),
    ("regression", "Other regression", "s-reg"),
    ("unattributed", "Unattributed", "s-una"),
)
LINEAGE_LABEL = {key: label for key, label, _cls in LINEAGE}
ORIGIN_LABEL = {
    "code-review": "Code review",
    "full-code-review": "Full code review",
    "delivery-code-review": "Delivery review",
    "qa-sweep": "QA sweep",
    "qa-full-sweep": "Full QA sweep",
    "security-review": "Security review",
    "ci-failure-sweep": "CI failure sweep",
    "scanning-sweep": "Scanning sweeps",
    "review-reconciliation": "Review reconciliation",
    "friction-curation": "Friction curation",
    "other": "Untagged",
}
MEASURE_LABEL = {
    "code_added": "Code added",
    "code_deleted": "Code deleted",
    "tests_added": "Tests added",
    "tests_deleted": "Tests deleted",
    "other_added": "Other added",
    "other_deleted": "Other deleted",
    "net": "Net",
}
PART_LABEL = {
    "recovered": "recovered",
    "failed": "failed",
    "resume": "resumed",
    "settled": "settled",
    "escalated": "escalated",
    "other": "other",
    "failed_checks": "failed checks",
    "conflict": "conflict",
    "landing_review": "landing review",
    "pr_head": "PR heads",
    "sweep_filing": "sweep filings",
    "invocations": "invocations",
}
TOKEN_TIERS = ("low", "medium", "hard", "xhard")
# A tier average over fewer runs than this is flagged as a thin sample.
THIN_TIER_RUNS = 30
# Below this share of done tasks measured, a board carries a coverage warning.
COVERAGE_WARN_RATE = 0.5
GROUPS = (
    ("speed", "Speed", (("duration", "Duration"), ("turns", "Turns"))),
    ("throughput", "Throughput", (("completed", "Tasks completed"), ("outcomes", "Outcomes"))),
    ("quality", "Quality", (("defects", "Defects"), ("friction", "Friction"))),
    ("spend", "Spend", (("cost", "Cost"), ("tokens", "Tokens"), ("diff", "Lines"))),
)
EVENT_FAMILIES = ("step_recovery", "final_recovery", "auto_fix", "merge_conflict", "failed_ci")
SCOPE_LABEL = {"all_time": "all time"}

HEADER = """<header>
  <div class="wrap bar">
    <a class="brand" href="/">
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <mask id="hm" maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100">
          <rect width="100" height="100" fill="#fff"/>
          <circle cx="23.87" cy="47.41" r="7.6" fill="#000"/>
          <circle cx="74.62" cy="63.52" r="8" fill="#000"/>
        </mask>
        <g mask="url(#hm)" fill="none" stroke="currentColor" stroke-width="3.4">
          <ellipse cx="50" cy="50" rx="34" ry="19" transform="rotate(-28 50 50)"/>
          <ellipse cx="50" cy="50" rx="45" ry="25" transform="rotate(-28 50 50)"/>
        </g>
        <g fill="currentColor">
          <circle cx="23.87" cy="47.41" r="5.2"/>
          <circle cx="74.62" cy="63.52" r="5.6"/>
        </g>
      </svg>
      <b>constellation<span> works</span></b>
    </a>
    <nav>
      <a href="/notes/">Notes</a>
      <a href="/ranking/">Ranking</a>
      <a href="/analytics/" aria-current="page">Analytics</a>
      <a class="nav-orbit" href="https://orbit-cli.com">Orbit</a>
      <a href="https://github.com/constellation-works">GitHub</a>
      <button class="theme" type="button" aria-label="Switch to light theme" hidden>
        <svg class="sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>
        <svg class="moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>
      </button>
    </nav>
  </div>
</header>"""


def e(value):
    return html.escape(str(value), quote=True)


# Monthly snapshot archive. The archive starts at the first routine snapshot
# (2026-11-08); nothing earlier is backfilled. A month becomes an archive
# entry once a snapshot from a later month exists, i.e. once that month has
# ended; the newest snapshot's own month is the live "Latest" page.
ARCHIVE_FLOOR = datetime.date(2026, 11, 8)
_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


def _snapshot_dirs(base):
    base = pathlib.Path(base)
    if not base.is_dir():
        return []
    dated = []
    for path in base.iterdir():
        if not path.is_dir() or not DAY.fullmatch(path.name):
            continue
        try:
            day = datetime.date.fromisoformat(path.name)
        except ValueError:
            continue
        dated.append((day, path))
    return sorted(dated)


def _window_label(page):
    """(label, pointer) for a snapshot entry's picker/banner window.

    Pages with one window name it directly. Multi-window pages keep the
    shared fleet reliability range only as an explicitly labelled reference
    and point at the per-board / cumulative windows on the page itself.
    """
    if page == "reliability":
        return "fleet reliability window", None
    if page == "metrics":
        return "metrics window", "a board prints its own window only where it differs"
    if page == "experiments":
        return (
            "fleet reliability reference window",
            "each experiment shows its cumulative observation window",
        )
    return (
        "fleet reliability reference window",
        "each board shows its own observation window",
    )


def _read_snapshot_json(directory, name):
    try:
        data = json.loads((pathlib.Path(directory) / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _window_stamps(directory, page=None):
    """Validated (since, until) stamps for a snapshot, or (None, None).

    The stamps are page-specific where a page has a single window:
    reliability reads its own window and metrics reads the metrics
    durations window. Agents and experiments have no single observation
    window (settled reviewers, tier boards and cumulative experiments all
    differ), so they fall back to meta.json's fleet reliability window,
    which callers must label as a reference via _window_label. Anything
    unparseable is ignored rather than published.
    """
    directory = pathlib.Path(directory)
    meta_windows = _read_snapshot_json(directory, "meta.json").get("windows") or {}
    if not isinstance(meta_windows, dict):
        meta_windows = {}
    if page == "reliability":
        candidates = [
            _read_snapshot_json(directory, "reliability.json").get("window"),
            meta_windows.get("reliability"),
        ]
    elif page == "metrics":
        metrics = _read_snapshot_json(directory, "metrics.json")
        candidates = [
            (metrics.get("durations") or {}).get("window")
            if isinstance(metrics.get("durations"), dict) else None,
            meta_windows.get("metrics"),
        ]
    else:
        candidates = [
            meta_windows.get("reliability"),
            _read_snapshot_json(directory, "reliability.json").get("window"),
        ]
    for window in candidates:
        if not isinstance(window, dict):
            continue
        since, until = window.get("since"), window.get("until")
        if not (isinstance(since, str) and isinstance(until, str)
                and _STAMP.fullmatch(since) and _STAMP.fullmatch(until)):
            continue
        try:
            if parse_time(since) <= parse_time(until):
                return since, until
        except (ValueError, OverflowError):
            continue
    return None, None


def snapshot_entry(directory, page=None):
    directory = pathlib.Path(directory)
    since, until = _window_stamps(directory, page)
    label, note = _window_label(page)
    return {
        "month": directory.name[:7],
        "date": directory.name,
        "directory": directory,
        "since": since,
        "until": until,
        "page": page,
        "window_label": label,
        "window_note": note,
    }


def latest_snapshot_entry(base, required=None, page=None):
    dated = _snapshot_dirs(base)
    if required:
        dated = [(day, path) for day, path in dated if (path / required).is_file()]
    return snapshot_entry(dated[-1][1], page) if dated else None


def monthly_archive_entries(base, required=None, page=None):
    """Latest snapshot of each closed calendar month, newest month first."""
    dated = _snapshot_dirs(base)
    if not dated:
        return []
    open_month = dated[-1][0].isoformat()[:7]
    by_month = {}
    for day, path in dated:
        if day < ARCHIVE_FLOOR:
            continue
        if required and not (path / required).is_file():
            continue
        by_month[day.isoformat()[:7]] = path
    months = sorted((m for m in by_month if m < open_month), reverse=True)
    return [snapshot_entry(by_month[month], page) for month in months]


def month_label(month):
    return datetime.date(int(month[:4]), int(month[5:7]), 1).strftime("%B %Y")


def _window_html(entry, page=None):
    if not entry.get("since") or not entry.get("until"):
        return ""
    label, note = _window_label(page if page is not None else entry.get("page"))
    if page is None and entry.get("window_label"):
        label = entry["window_label"]
        note = entry.get("window_note")
    pointer = f" ({e(note)})" if note else ""
    return (
        f', {e(label)} <time datetime="{e(entry["since"])}">{e(entry["since"][:10])}</time>'
        f' to <time datetime="{e(entry["until"])}">{e(entry["until"][:10])}</time>{pointer}'
    )


def snapshot_picker(page, latest, archives, current=None):
    """No-JS link list: Latest plus each archived month, newest first.

    Every date sits inside a <time> element, and the current entry carries
    aria-current plus visible "(current)" text.
    """
    if latest is None:
        return ""

    def mark(is_current):
        return (
            ' aria-current="page" class="is-current"', ' <span class="snapshot-current">(current)</span>'
        ) if is_current else ("", "")

    def window_title(entry):
        if not entry.get("since") or not entry.get("until"):
            return ""
        label, note = _window_label(page)
        pointer = f" ({note})" if note else ""
        return f', {label} {entry["since"][:10]} to {entry["until"][:10]}{pointer}'

    attrs, suffix = mark(current is None)
    latest_date_text = latest["date"]
    latest_date = e(latest_date_text)
    latest_title = e(f"Latest snapshot {latest_date_text}{window_title(latest)}")
    items = [
        f'<li><a href="/analytics/{e(page)}/"{attrs}'
        f' title="{latest_title}">'
        f'Latest · <time datetime="{latest_date}">{latest_date}</time></a>{suffix}</li>'
    ]
    for entry in archives:
        attrs, suffix = mark(current == entry["month"])
        month_text = month_label(entry["month"])
        month = e(month_text)
        archive_title = e(f"{month_text} snapshot {entry['date']}{window_title(entry)}")
        items.append(
            f'<li><a href="/analytics/{e(page)}/{e(entry["month"])}/"{attrs}'
            f' title="{archive_title}">'
            f'{month}</a>{suffix}</li>'
        )
    return (
        '<nav class="snapshot-picker" aria-label="Snapshot months">'
        '<span class="snapshot-picker-label">Snapshot</span><ul>'
        + "".join(items)
        + "</ul></nav>"
    )


def archive_banner(page, entry):
    return (
        '<p class="archive-banner">Historical snapshot: this page shows the '
        f'<time datetime="{e(entry["month"])}">{e(month_label(entry["month"]))}</time> snapshot from '
        f'<time datetime="{e(entry["date"])}">{e(entry["date"])}</time>{_window_html(entry, page)}. '
        f'<a href="/analytics/{e(page)}/">Back to Latest</a>.</p>'
    )


def picker_html(base, page, required=None, current=None):
    return snapshot_picker(
        page,
        latest_snapshot_entry(base, required, page),
        monthly_archive_entries(base, required, page),
        current,
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


def section_duration(metrics):
    durations = metrics["durations"]
    current = durations.get("current") or {}
    previous = durations.get("previous") or {}
    buckets = durations.get("buckets") or []
    window = durations.get("window") or {}
    tier_cards = []
    for key in ("all", "low", "medium", "hard", "xhard"):
        cell = current.get(key)
        if not isinstance(cell, dict):
            continue
        prefix = f"durations.current.{key}"
        value = fig(format_ms(cell.get("avg")), "duration", f"{prefix}.avg", cls="value")
        bits = [fig(unit_count(cell.get("n"), "runs"), "runs", f"{prefix}.n")]
        prev = previous.get(key) if isinstance(previous.get(key), dict) else None
        if prev is not None:
            bits.append(delta_fig(cell.get("avg"), prev.get("avg"), "duration", f"{prefix}.avg", f"durations.previous.{key}.avg"))
            bits.append("previous " + fig(format_ms(prev.get("avg")), "duration", f"durations.previous.{key}.avg"))
        detail = " · ".join(bits)
        detail += "<br>" + '<span class="label">p50</span> ' + fig(format_ms(cell.get("p50")), "duration", f"{prefix}.p50")
        detail += " · " + '<span class="label">p95</span> ' + fig(format_ms(cell.get("p95")), "duration", f"{prefix}.p95")
        tier_cards.append(score_card(TIER_LABEL[key], value, detail))
    line_series = [{
        "cls": f"s-{key}",
        "field": f"durations.buckets.{key}.avg",
        "values": bucket_stat(buckets, key, "avg", "minutes"),
    } for key in DURATION_LINES]
    volume = [{
        "cls": cls,
        "field": "durations.buckets.other_runs" if key == "other_runs" else f"durations.buckets.{key}.n",
        "values": [float(bucket.get("other_runs") or 0) for bucket in buckets] if key == "other_runs"
        else [float((bucket.get(key) or {}).get("n") or 0) for bucket in buckets],
    } for key, cls in VOLUME_STACK]
    first, last = _ends(buckets, "start")
    chart = line_chart(
        line_series, "minutes", "Average duration of implement_one runs that finished each UTC day",
        first, last, "durations.buckets.0.start", f"durations.buckets.{len(buckets) - 1}.start",
    ) if buckets else ""
    bars = stack_chart(
        volume, "count", "implement_one runs that finished each UTC day",
        first, last, "durations.buckets.0.start", f"durations.buckets.{len(buckets) - 1}.start",
    ) if buckets else ""
    daily_rows = []
    for index, bucket in reversed(list(enumerate(buckets))):
        cells = [f"<td>{day_cell(bucket.get('start'), f'durations.buckets.{index}.start')}</td>"]
        for key in DURATION_LINES:
            cell = bucket.get(key)
            if not isinstance(cell, dict) or cell.get("avg") is None:
                cells.append("<td>—</td>")
                continue
            cells.append(
                "<td>"
                + fig(format_ms(cell.get("avg")), "duration", f"durations.buckets.{index}.{key}.avg")
                + " · "
                + fig(unit_count(cell.get("n"), "runs"), "runs", f"durations.buckets.{index}.{key}.n")
                + "</td>"
            )
        daily_rows.append("".join(cells))
    daily = more("Daily figures, newest first", table(
        "Average duration and runs per UTC day, newest first.",
        ["Day", "All", "Low", "Medium", "Hard"],
        daily_rows,
        more_label="days",
        preview=False,
    )) if daily_rows else ""
    thin = []
    for key in ("low", "medium", "hard", "xhard"):
        cell = current.get(key)
        if isinstance(cell, dict) and isinstance(cell.get("n"), int) and 0 < cell["n"] < THIN_TIER_RUNS:
            thin.append(
                f"{e(TIER_LABEL[key])} has only "
                + fig(unit_count(cell["n"], "runs"), "runs", f"durations.current.{key}.n")
            )
    warning = warn("Thin sample", "; ".join(thin) + ". Read those averages as a small sample.") if thin else ""
    actors = _actor_table(durations.get("actors") or [], "durations.actors", with_trend=True)
    by_complexity = []
    for index, band in enumerate(durations.get("implement_one_by_complexity") or []):
        label = TIER_LABEL.get(band.get("complexity"), band.get("complexity") or "Tier")
        count = fig(unit_count(band.get("n"), "runs"), "runs", f"durations.implement_one_by_complexity.{index}.n")
        by_complexity.append(
            f"<h4>{e(label)}</h4><p class=\"detail\">{count}</p>"
            + _actor_table(band.get("actors") or [], f"durations.implement_one_by_complexity.{index}.actors", with_trend=False)
        )
    outcome = text_fig(durations.get("outcome"), "durations.outcome")
    intro = (
        f"Average wall-clock time of implement_one runs with outcome {outcome}. "
        "Counted: final implement_one attempts in successful runs with a committed candidate. "
        "Failed, cancelled, no-diff and unknown outcomes are excluded. "
        "Extra hard runs are included in All and omitted from the low, medium and hard lines."
    )
    actor_count = len(durations.get("actors") or [])
    body = "".join([
        board_window(window, "durations.window", metrics),
        warning,
        cards(tier_cards),
        "<h4>Average by day</h4>",
        legend([(f"s-{key}", TIER_LABEL[key], "line") for key in DURATION_LINES]),
        chart,
        "<h4>Runs by day</h4>",
        legend([("s-low", "Low", "bar"), ("s-medium", "Medium", "bar"), ("s-hard", "Hard", "bar"), ("s-other", "Other", "bar")]),
        bars,
        daily,
        more(f"By model ({actor_count} models)",
             "<p class=\"detail\">Sorted by runs. Dimmed rows are a small sample and are not ranked.</p>" + actors),
        more("By model within a complexity", "".join(by_complexity)),
    ])
    return section("duration", "Duration", intro, body)


def _ends(rows, key):
    if not rows:
        return None, None
    return rows[0].get(key), rows[-1].get(key)


def _actor_table(actors, prefix, with_trend):
    if not actors:
        return "<p class=\"detail\">No model rows in this window.</p>"
    order = sorted(range(len(actors)), key=lambda index: (-(actors[index].get("n") or 0), actors[index].get("actor") or ""))
    headers = ["Model", "Runs", "Average", '<span class="label">p50</span>', '<span class="label">p95</span>']
    if with_trend:
        headers.extend(["Previous average", "Change", "Trend"])
    rows = []
    for index in order:
        actor = actors[index]
        dim = " class=\"dim\"" if (actor.get("n") or 0) < LOW_ACTOR_SAMPLE else ""
        cells = [
            f"<th scope=\"row\"{dim}>{text_fig(actor.get('actor'), f'{prefix}.{index}.actor')}</th>",
            "<td>" + fig(unit_count(actor.get("n"), "runs"), "runs", f"{prefix}.{index}.n") + "</td>",
            "<td>" + fig(format_ms(actor.get("avg")), "duration", f"{prefix}.{index}.avg") + "</td>",
            "<td>" + fig(format_ms(actor.get("p50")), "duration", f"{prefix}.{index}.p50") + "</td>",
            "<td>" + fig(format_ms(actor.get("p95")), "duration", f"{prefix}.{index}.p95") + "</td>",
        ]
        if with_trend:
            if "previous_avg" in actor:
                cells.append("<td>" + fig(format_ms(actor.get("previous_avg")), "duration", f"{prefix}.{index}.previous_avg") + "</td>")
                cells.append("<td>" + delta_fig(actor.get("avg"), actor.get("previous_avg"), "duration", f"{prefix}.{index}.avg", f"{prefix}.{index}.previous_avg") + "</td>")
            else:
                cells.extend(["<td>—</td>", "<td>—</td>"])
            trend = actor.get("trend") or []
            cells.append("<td>" + sparkline(trend, f"{prefix}.{index}.trend") + "</td>")
        rows.append("".join(cells))
    return table("", headers, rows)


def section_completions(metrics):
    completions = metrics["completions"]
    current = completions.get("current") or {}
    previous = completions.get("previous") or {}
    done = current.get("done") or {}
    prev_done = previous.get("done") or {}
    buckets = completions.get("buckets") or []
    window = completions.get("window") or {}
    tier_cards = []
    total_field = "completions.current.done.total"
    value = fig(unit_count(done.get("total"), "tasks"), "tasks", total_field, cls="value")
    bits = []
    if prev_done:
        bits.append(delta_fig(done.get("total"), prev_done.get("total"), "better", total_field, "completions.previous.done.total"))
    bits.append(fig(unit_count(current.get("rejected"), "rejected"), "rejected", "completions.current.rejected"))
    bits.append(fig(unit_count(current.get("archived"), "archived"), "archived", "completions.current.archived"))
    tier_cards.append(score_card("Done", value, " · ".join(bits)))
    for key in ("low", "medium", "hard", "other"):
        field = f"completions.current.done.{key}"
        card_value = fig(unit_count(done.get(key), "tasks"), "tasks", field, cls="value")
        detail = fig(format_share(done.get(key), done.get("total")), "share", field, base=total_field)
        if prev_done:
            detail += " · " + delta_fig(done.get(key), prev_done.get(key), "better", field, f"completions.previous.done.{key}")
        tier_cards.append(score_card(TIER_LABEL.get(key, key), card_value, detail))
    series = []
    for key, cls in DONE_STACK:
        series.append({
            "cls": cls,
            "field": f"completions.buckets.done.{key}",
            "values": [float((bucket.get("done") or {}).get(key) or 0) for bucket in buckets],
        })
    first, last = _ends(buckets, "start")
    chart = stack_chart(
        series, "count", "Tasks moved to done each UTC day",
        first, last, "completions.buckets.0.start", f"completions.buckets.{len(buckets) - 1}.start",
    ) if buckets else ""
    rows = []
    for index, bucket in reversed(list(enumerate(buckets))):
        done_row = bucket.get("done") or {}
        cells = [f"<td>{day_cell(bucket.get('start'), f'completions.buckets.{index}.start')}</td>"]
        for key in ("total", "low", "medium", "hard", "other"):
            cells.append("<td>" + fig(unit_count(done_row.get(key), "tasks"), "tasks", f"completions.buckets.{index}.done.{key}") + "</td>")
        cells.append("<td>" + fig(unit_count(bucket.get("archived"), "archived"), "archived", f"completions.buckets.{index}.archived") + "</td>")
        cells.append("<td>" + fig(unit_count(bucket.get("rejected"), "rejected"), "rejected", f"completions.buckets.{index}.rejected") + "</td>")
        rows.append("".join(cells))
    daily = more("Daily figures, newest first", table(
        "Tasks closed per UTC day, newest first. Extra hard and unset are in Done and in Other.",
        ["Day", "Done", "Low", "Medium", "Hard", "Other", "Archived", "Rejected"],
        rows,
        more_label="days",
        preview=False,
    )) if rows else ""
    intro = "Tasks that moved to done in each UTC day, by complexity. This board is not filtered by run outcome."
    body = "".join([
        board_window(window, "completions.window", metrics),
        cards(tier_cards),
        legend([("s-low", "Low", "bar"), ("s-medium", "Medium", "bar"), ("s-hard", "Hard", "bar"), ("s-other", "Other", "bar")]),
        chart,
        daily,
    ])
    return section("completed", "Tasks completed", intro, body)


def section_defects(metrics):
    defects = metrics["defects"]
    current = defects.get("current") or {}
    previous = defects.get("previous") or {}
    lineage = current.get("lineage") or {}
    prev_lineage = previous.get("lineage") or {}
    origin = current.get("origin") or {}
    buckets = defects.get("buckets") or []
    window = defects.get("window") or {}
    total_field = "defects.current.total"
    headline = score_card(
        "Defects",
        fig(unit_count(current.get("total"), "defects"), "defects", total_field, cls="value"),
        delta_fig(current.get("total"), previous.get("total"), "worse", total_field, "defects.previous.total")
        + " · previous " + fig(unit_count(previous.get("total"), "defects"), "defects", "defects.previous.total"),
    )
    lineage_cards = []
    for key, label, _cls in LINEAGE:
        field = f"defects.current.lineage.{key}"
        detail = fig(format_ratio(lineage.get(key), current.get("total")), "ratio", field, base=total_field)
        if prev_lineage:
            detail += " · " + delta_fig(lineage.get(key), prev_lineage.get(key), "worse", field, f"defects.previous.lineage.{key}")
        lineage_cards.append(score_card(
            label,
            fig(unit_count(lineage.get(key), "defects"), "defects", field, cls="value"),
            detail,
        ))
    series = []
    for key, _label, cls in LINEAGE:
        series.append({
            "cls": cls,
            "field": f"defects.buckets.lineage.{key}",
            "values": [float((bucket.get("lineage") or {}).get(key) or 0) for bucket in buckets],
        })
    first, last = _ends(buckets, "start")
    chart = stack_chart(
        series, "count", "Defects filed each UTC day, by lineage",
        first, last, "defects.buckets.0.start", f"defects.buckets.{len(buckets) - 1}.start",
    ) if buckets else ""
    origin_rows = []
    for key, count in sorted(origin.items(), key=lambda item: (-(item[1] or 0), item[0])):
        field = f"defects.current.origin.{key}"
        origin_rows.append("".join([
            f"<th scope=\"row\">{e(ORIGIN_LABEL.get(key, key))}</th>",
            "<td>" + fig(unit_count(count, "defects"), "defects", field) + "</td>",
            "<td>" + fig(format_ratio(count, current.get("total")), "ratio", field, base=total_field) + "</td>",
        ]))
    origin_table = table("Where the defect was filed.", ["Origin", "Defects", "Share of total"], origin_rows)
    daily_rows = []
    for index, bucket in reversed(list(enumerate(buckets))):
        cells = [f"<td>{day_cell(bucket.get('start'), f'defects.buckets.{index}.start')}</td>"]
        cells.append("<td>" + fig(unit_count(bucket.get("total"), "defects"), "defects", f"defects.buckets.{index}.total") + "</td>")
        for key, _label, _cls in LINEAGE:
            cells.append("<td>" + fig(unit_count((bucket.get("lineage") or {}).get(key), "defects"), "defects", f"defects.buckets.{index}.lineage.{key}") + "</td>")
        daily_rows.append("".join(cells))
    daily = more("Daily figures, newest first", table(
        "Defects per UTC day, newest first.",
        ["Day", "Total", "Fix-for-a-fix", "Other regression", "Unattributed"],
        daily_rows,
        more_label="days",
        preview=False,
    )) if daily_rows else ""
    done_now = ((metrics.get("completions") or {}).get("current") or {}).get("done") or {}
    done_prev = ((metrics.get("completions") or {}).get("previous") or {}).get("done") or {}
    rate_now = per_done(current.get("total"), done_now.get("total"))
    rate_prev = per_done(previous.get("total"), done_prev.get("total"))
    per_done_card = ""
    if rate_now is not None:
        detail = "defects filed ÷ tasks done"
        if rate_prev is not None:
            detail = from_delta(rate_now, rate_prev, "worse", fig(
                format_per_done(previous.get("total"), done_prev.get("total")), "per-done",
                "defects.previous.total", base="completions.previous.done.total",
            )) + " · " + detail
        per_done_card = score_card("Per done task *", fig(
            format_per_done(current.get("total"), done_now.get("total")), "per-done",
            total_field, cls="value", base="completions.current.done.total",
        ), detail)
    intro = "Defects filed in the window, by what caused them and by what found them. A rise is a worse result."
    body = "".join([
        board_window(window, "defects.window", metrics),
        cards([headline, *([per_done_card] if per_done_card else []), *lineage_cards]),
        legend([(cls, label, "bar") for _key, label, cls in LINEAGE]),
        chart,
        daily,
        "<h4>By origin</h4>",
        origin_table,
    ])
    return section("defects", "Defects", intro, body)


def _series_index(series, complexity, cohort="all"):
    for index, item in enumerate(series or []):
        if item.get("complexity") == complexity and item.get("cohort") == cohort:
            return index
    return None


def from_delta(current, previous, mode, previous_fig):
    """'▼ from <previous>' for a figure whose change is shown against a previous level."""
    cls = delta_class(current, previous, mode)
    arrow = "▲" if current is not None and previous is not None and current > previous else "▼"
    if current is not None and previous is not None and current == previous:
        arrow = "="
    return f'<span class="delta {cls}">{arrow} from {previous_fig}</span>'


def turns_warning(coverage):
    rate = coverage.get("measured_rate")
    if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate >= COVERAGE_WARN_RATE:
        return ""
    return warn(
        "Thin coverage",
        "Only " + fig(unit_count(coverage.get("measured"), "tasks"), "tasks", "turns.coverage.measured")
        + " of " + fig(unit_count(coverage.get("tasks"), "tasks"), "tasks", "turns.coverage.tasks")
        + " (" + fig(format_percent(rate), "percent", "turns.coverage.measured_rate")
        + ") had a measurable first edit. Read these figures as a sample, not the fleet.",
    )


def tokens_warning(metrics):
    total = (metrics.get("tokens") or {}).get("total") or {}
    measured = total.get("n")
    uncovered = total.get("excluded_uncovered")
    silent = total.get("excluded_no_invocations")
    numbers = [measured, uncovered, silent]
    if any(not isinstance(v, int) or isinstance(v, bool) for v in numbers):
        return ""
    excluded = uncovered + silent
    if not excluded or excluded * 10 < measured + excluded:
        return ""
    return warn(
        "Partial coverage",
        fig(unit_count(uncovered, "tasks"), "tasks", "tokens.total.excluded_uncovered")
        + " had no token coverage and "
        + fig(unit_count(silent, "tasks"), "tasks", "tokens.total.excluded_no_invocations")
        + " had no invocations; they are left out of the means, which cover "
        + fig(unit_count(measured, "tasks"), "tasks", "tokens.total.n") + ".",
    )


def cost_warning(index, total):
    excluded = total.get("excluded_invocations")
    if not isinstance(excluded, int) or isinstance(excluded, bool) or excluded <= 0:
        return ""
    return warn(
        "Partial coverage",
        fig(unit_count(excluded, "invocations"), "invocations", f"friction.families.{index}.total.excluded_invocations")
        + " are excluded from this total; the snapshot does not say what they cost.",
    )


def section_tokens(metrics):
    tokens = metrics["tokens"]
    total = tokens.get("total") or {}
    window = tokens.get("window") or {}
    series = tokens.get("series") or []
    starts = tokens.get("bucket_starts") or []
    headline_bits = [
        fig(unit_count(total.get("n"), "tasks"), "tasks", "tokens.total.n"),
        "median " + fig(unit_count(total.get("median"), "tokens"), "tokens", "tokens.total.median"),
        "sum " + fig(unit_count(total.get("sum"), "tokens"), "tokens", "tokens.total.sum"),
    ]
    headline = score_card(
        "Mean tokens",
        fig(unit_count(total.get("mean"), "tokens"), "tokens", "tokens.total.mean", cls="value"),
        " · ".join(headline_bits),
    )
    extra = score_card(
        "Excluded",
        fig(unit_count(total.get("excluded_uncovered"), "tasks"), "tasks", "tokens.total.excluded_uncovered", cls="value"),
        "uncovered · "
        + fig(unit_count(total.get("excluded_no_invocations"), "tasks"), "tasks", "tokens.total.excluded_no_invocations")
        + " with no invocations",
    )
    tier_cards = [headline, extra]
    line_series = []
    for key in TOKEN_TIERS:
        index = _series_index(series, key)
        if index is None:
            continue
        item = series[index]
        cell = item.get("total") or {}
        field = f"tokens.series.{index}.total.mean"
        detail = fig(unit_count(cell.get("n"), "tasks"), "tasks", f"tokens.series.{index}.total.n")
        detail += " · median " + fig(unit_count(cell.get("median"), "tokens"), "tokens", f"tokens.series.{index}.total.median")
        tier_cards.append(score_card(
            TIER_LABEL.get(key, key),
            fig(unit_count(cell.get("mean"), "tokens"), "tokens", field, cls="value"),
            detail,
        ))
        line_series.append({
            "cls": f"s-{key}",
            "field": f"tokens.series.{index}.points.mean",
            "values": [chart_value((point or {}).get("mean"), "tokens") for point in item.get("points") or []],
        })
    unset = _series_index(series, "unset")
    if unset is not None:
        cell = (series[unset].get("total") or {})
        tier_cards.append(score_card(
            "Unset",
            fig(unit_count(cell.get("mean"), "tokens"), "tokens", f"tokens.series.{unset}.total.mean", cls="value"),
            fig(unit_count(cell.get("n"), "tasks"), "tasks", f"tokens.series.{unset}.total.n")
            + (" · thin sample" if cell.get("thin") else ""),
        ))
    first = starts[0] if starts else None
    last = starts[-1] if starts else None
    chart = line_chart(
        line_series, "tokens", "Mean tokens per task each UTC day, by complexity",
        first, last, "tokens.bucket_starts.0", f"tokens.bucket_starts.{len(starts) - 1}",
    ) if line_series else ""
    models = tokens.get("available_models") or []
    order = sorted(range(len(models)), key=lambda index: (-(models[index].get("tasks") or 0), models[index].get("model") or ""))
    model_rows = []
    for index in order:
        model = models[index]
        model_rows.append("".join([
            f"<th scope=\"row\">{text_fig(model.get('model'), f'tokens.available_models.{index}.model')}</th>",
            "<td>" + fig(unit_count(model.get("tasks"), "tasks"), "tasks", f"tokens.available_models.{index}.tasks") + "</td>",
        ]))
    model_table = table(
        "Tasks by model. The means above pool every model; the snapshot has no per-model token mean.",
        ["Model", "Tasks"],
        model_rows,
        preview=False,
    ) if model_rows else ""
    outcome = text_fig(tokens.get("outcome"), "tokens.outcome")
    scope = fig(format_scope(tokens.get("scope")), "scope", "tokens.scope")
    intro = f"Tokens per task with outcome {outcome}, scope {scope}. This is not the succeeded-run filter used for duration."
    body = "".join([
        board_window(window, "tokens.window", metrics),
        tokens_warning(metrics),
        cards(tier_cards),
        legend([(f"s-{key}", TIER_LABEL[key], "line") for key in TOKEN_TIERS]),
        chart,
        more(f"Tasks by model ({len(model_rows)} models)", model_table),
    ])
    return section("tokens", "Tokens", intro, body)


def _family(metrics, name):
    for index, family in enumerate((metrics.get("friction") or {}).get("families") or []):
        if family.get("family") == name:
            return index, family
    return None, None


def _family_count(index, family):
    return fig(
        format_usd(family["total"]["count"]) if family.get("unit") == "usd" else unit_count(family["total"]["count"], family.get("unit") or "events"),
        "family-count",
        f"friction.families.{index}.total.count",
        cls="value",
        unit=f"friction.families.{index}.unit",
    )


def section_cost(metrics):
    index, family = _family(metrics, "cost")
    if family is None:
        return ""
    window = (metrics.get("friction") or {}).get("window") or {}
    total = family.get("total") or {}
    previous = family.get("previous") or {}
    detail = fig(_usd_per(total.get("rate")), "usd-per", f"friction.families.{index}.total.rate")
    detail += " · " + fig(unit_count(total.get("denominator"), "tasks"), "tasks", f"friction.families.{index}.total.denominator") + " done"
    if previous:
        detail += " · " + delta_fig(total.get("count"), previous.get("count"), "worse", f"friction.families.{index}.total.count", f"friction.families.{index}.previous.count")
        detail += " · previous " + fig(format_usd(previous.get("count")), "usd", f"friction.families.{index}.previous.count")
    invocations = (total.get("breakdown") or {}).get("invocations")
    if invocations is not None:
        detail += " · " + fig(format_usd(invocations), "usd", f"friction.families.{index}.total.breakdown.invocations") + " invocations"
    excluded = total.get("excluded_invocations")
    if excluded is not None:
        detail += " · " + fig(unit_count(excluded, "invocations"), "invocations", f"friction.families.{index}.total.excluded_invocations") + " excluded"
    points = family.get("points") or []
    starts = (metrics.get("friction") or {}).get("bucket_starts") or []
    chart = line_chart(
        [{
            "cls": "s-cost",
            "field": f"friction.families.{index}.points.count",
            "values": [chart_value((point or {}).get("count"), "usd") for point in points],
        }],
        "usd",
        "Cost in USD each UTC day",
        starts[0] if starts else None,
        starts[-1] if starts else None,
        "friction.bucket_starts.0",
        f"friction.bucket_starts.{len(starts) - 1}",
    ) if points else ""
    intro = "Spend recorded on the delivery-friction board, in USD, for tasks that reached done. A rise is a worse result."
    body = "".join([
        board_window(window, "friction.window", metrics),
        cost_warning(index, total),
        cards([score_card("Cost", _family_count(index, family), detail)]),
        legend([("s-cost", "Cost", "line")]),
        chart,
    ])
    return section("cost", "Cost", intro, body)


def _usd_per(value):
    if value is None or isinstance(value, bool):
        return "—"
    return f"{float(value):,.2f} USD per done task"


def section_diff(metrics):
    diff = metrics["diff"]
    overall = (diff.get("overall") or {}).get("total") or {}
    window = diff.get("window") or {}
    measures = diff.get("measures") or list(MEASURE_LABEL)
    measure_rows = []
    for measure in measures:
        if measure not in MEASURE_LABEL:
            continue
        mean = (overall.get("mean") or {}).get(measure)
        median = (overall.get("median") or {}).get(measure)
        total = (overall.get("sum") or {}).get(measure)
        measure_rows.append("".join([
            f"<th scope=\"row\">{e(MEASURE_LABEL[measure])}</th>",
            "<td>" + fig(format_lines(mean), "lines", f"diff.overall.total.mean.{measure}") + "</td>",
            "<td>" + fig(format_lines(median), "lines", f"diff.overall.total.median.{measure}") + "</td>",
            "<td>" + fig(format_lines(total), "lines", f"diff.overall.total.sum.{measure}") + "</td>",
        ]))
    deliveries = fig(unit_count(overall.get("n"), "deliveries"), "deliveries", "diff.overall.total.n", cls="value")
    points = (diff.get("overall") or {}).get("points") or []
    starts = diff.get("bucket_starts") or []
    chart = line_chart(
        [{
            "cls": "s-all",
            "field": "diff.overall.points.mean.net",
            "values": [chart_value(((point or {}).get("mean") or {}).get("net"), "lines") for point in points],
        }],
        "lines",
        "Mean net lines of deliveries that landed each UTC day",
        starts[0] if starts else None,
        starts[-1] if starts else None,
        "diff.bucket_starts.0",
        f"diff.bucket_starts.{len(starts) - 1}",
    ) if points else ""
    crews = diff.get("crews") or []
    order = sorted(range(len(crews)), key=lambda index: (-((crews[index].get("total") or {}).get("n") or 0), crews[index].get("key") or ""))
    means = []
    for index in order:
        mean = (((crews[index].get("total") or {}).get("mean") or {}).get("net"))
        if mean is not None:
            means.append(float(mean))
    y_max = nice_ceiling(max(means) if means else 0)
    plot_w = 280
    bar_rows = []
    crew_rows = []
    for index in order:
        crew = crews[index]
        total = crew.get("total") or {}
        mean = (total.get("mean") or {}).get("net")
        width = bar_width(mean or 0, y_max, plot_w)
        names = crew.get("crews") or []
        # A one-name pool repeats the crew key. Show the members when the pool is wider.
        name_html = ""
        if names != [crew.get("key")]:
            name_html = " ".join(
                text_fig(name, f"diff.crews.{index}.crews.{name_index}") for name_index, name in enumerate(names)
            )
        bar_rows.append(
            "<div class=\"hbar\">"
            f"<span class=\"hbar-label\">{text_fig(crew.get('key'), f'diff.crews.{index}.key')}</span>"
            f'<svg class="hbar-plot" viewBox="0 0 {plot_w} 14" data-unit="lines" data-ymax="{y_max:g}" data-plot-w="{plot_w}" role="img" aria-label="Mean net lines">'
            f'<rect class="bar s-low" data-field="diff.crews.{index}.total.mean.net" x="0" y="2" width="{width:.2f}" height="10"></rect>'
            "</svg>"
            + fig(format_lines(mean), "lines", f"diff.crews.{index}.total.mean.net")
            + "</div>"
        )
        thin = " class=\"dim\"" if total.get("thin") or (total.get("n") or 0) < (diff.get("min_deliveries") or 0) else ""
        crew_rows.append("".join([
            f"<th scope=\"row\"{thin}>{text_fig(crew.get('key'), f'diff.crews.{index}.key')} {name_html}</th>",
            "<td>" + fig(unit_count(total.get("n"), "deliveries"), "deliveries", f"diff.crews.{index}.total.n") + "</td>",
            "<td>" + fig(format_lines((total.get("mean") or {}).get("net")), "lines", f"diff.crews.{index}.total.mean.net") + "</td>",
            "<td>" + fig(format_lines((total.get("mean") or {}).get("code_added")), "lines", f"diff.crews.{index}.total.mean.code_added") + "</td>",
            "<td>" + fig(format_lines((total.get("median") or {}).get("net")), "lines", f"diff.crews.{index}.total.median.net") + "</td>",
        ]))
    min_note = ""
    if diff.get("min_deliveries") is not None:
        min_note = "<p class=\"detail\">Dimmed crews are under " + fig(unit_count(diff.get("min_deliveries"), "deliveries"), "deliveries", "diff.min_deliveries") + " or marked thin, and are not ranked.</p>"
    intro = "Lines added and deleted by deliveries that landed in the window, split into code, tests and other files. Crews are the implementing crews."
    body = "".join([
        board_window(window, "diff.window", metrics),
        cards([score_card("Deliveries", deliveries, "Mean net " + fig(format_lines((overall.get("mean") or {}).get("net")), "lines", "diff.overall.total.mean.net"))]),
        legend([("s-all", "Mean net lines", "line")]),
        chart,
        more("By line kind", table("", ["Kind", "Mean", "Median", "Sum"], measure_rows, preview=False)),
        "<h4>By crew</h4>",
        min_note,
        f'<div class="hbars" data-ymax="{y_max:g}">{"".join(bar_rows)}</div>',
        more("Crew details", table("Mean lines per delivery, by crew.", ["Crew", "Deliveries", "Mean net", "Mean code added", "Median net"], crew_rows, preview=False)),
    ])
    return section("diff", "Lines changed", intro, body)


def section_friction(metrics):
    friction = metrics.get("friction") or {}
    families = friction.get("families") or []
    window = friction.get("window") or {}
    event_cards = []
    line_series = []
    palette = ["s-low", "s-medium", "s-hard", "s-reg", "s-fix"]
    for position, name in enumerate(EVENT_FAMILIES):
        index, family = _family(metrics, name)
        if family is None:
            continue
        total = family.get("total") or {}
        previous = family.get("previous") or {}
        detail = fig(format_percent(total.get("rate")), "percent", f"friction.families.{index}.total.rate")
        detail += " of " + fig(unit_count(total.get("denominator"), "tasks"), "tasks", f"friction.families.{index}.total.denominator") + " done"
        if previous:
            detail += " · " + delta_fig(total.get("count"), previous.get("count"), "worse", f"friction.families.{index}.total.count", f"friction.families.{index}.previous.count")
        parts = []
        for key, amount in (total.get("breakdown") or {}).items():
            parts.append(
                e(PART_LABEL.get(key, key)) + " " + fig(unit_count(amount, family.get("unit") or "events"), "events", f"friction.families.{index}.total.breakdown.{key}")
            )
        if parts:
            detail += "<br>" + " · ".join(parts)
        label = family.get("label") or name
        event_cards.append(score_card(label, _family_count(index, family), detail))
        line_series.append({
            "cls": palette[position % len(palette)],
            "field": f"friction.families.{index}.points.count",
            "values": [chart_value((point or {}).get("count"), "count") for point in family.get("points") or []],
        })
    starts = friction.get("bucket_starts") or []
    chart = line_chart(
        line_series, "count", "Delivery-friction events each UTC day",
        starts[0] if starts else None,
        starts[-1] if starts else None,
        "friction.bucket_starts.0",
        f"friction.bucket_starts.{len(starts) - 1}",
    ) if line_series else ""
    legend_items = []
    for position, name in enumerate(EVENT_FAMILIES):
        index, family = _family(metrics, name)
        if family is None:
            continue
        legend_items.append((palette[position % len(palette)], family.get("label") or name, "line"))
    crews = friction.get("available_crews") or []
    order = sorted(range(len(crews)), key=lambda index: (-(crews[index].get("tasks") or 0), crews[index].get("crew") or ""))
    crew_rows = []
    for index in order:
        crew = crews[index]
        crew_rows.append("".join([
            f"<th scope=\"row\">{text_fig(crew.get('crew'), f'friction.available_crews.{index}.crew')}</th>",
            "<td>" + fig(unit_count(crew.get("tasks"), "tasks"), "tasks", f"friction.available_crews.{index}.tasks") + "</td>",
        ]))
    crew_table = table(
        "Done tasks by crew. These are the crew totals on the friction board, not per-crew event rates.",
        ["Crew", "Tasks"],
        crew_rows,
        preview=False,
    ) if crew_rows else ""
    sparse = [family.get("label") or family.get("family") for family in families
              if isinstance(family, dict) and (family.get("total") or {}).get("sparse")]
    sparse_note = warn("Thin sample", e(", ".join(str(name) for name in sparse)) + " have too few events to compare.") if sparse else ""
    intro = (
        "Step recoveries, final recoveries, pull-request auto-fixes, merge conflicts and failed checks. "
        "Rates are events per task that reached done. Cost is in its own section. A rise is a worse result."
    )
    body = "".join([
        board_window(window, "friction.window", metrics),
        sparse_note,
        cards(event_cards),
        legend(legend_items),
        chart,
        more(f"Done tasks by crew ({len(crew_rows)} crews)", crew_table),
    ])
    return section("friction", "Delivery friction", intro, body)


def section_turns(metrics):
    turns = metrics["turns"]
    total = turns.get("total") or {}
    coverage = turns.get("coverage") or {}
    window = turns.get("window") or {}
    series = turns.get("series") or []
    starts = turns.get("bucket_starts") or []
    headline = score_card(
        "Mean turns",
        fig(format_turns(total.get("mean_turns")), "turns", "turns.total.mean_turns", cls="value"),
        "median " + fig(format_turns(total.get("median_turns")), "turns", "turns.total.median_turns")
        + " · " + fig(unit_count(total.get("n"), "tasks"), "tasks", "turns.total.n") + " measured",
    )
    bytes_card = score_card(
        "Result size",
        fig(unit_count(total.get("mean_result_bytes"), "B"), "bytes", "turns.total.mean_result_bytes", cls="value"),
        "median " + fig(unit_count(total.get("median_result_bytes"), "B"), "bytes", "turns.total.median_result_bytes"),
    )
    coverage_card = score_card(
        "Coverage",
        fig(format_percent(coverage.get("measured_rate")), "percent", "turns.coverage.measured_rate", cls="value"),
        fig(unit_count(coverage.get("measured"), "tasks"), "tasks", "turns.coverage.measured")
        + " measured of "
        + fig(unit_count(coverage.get("tasks"), "tasks"), "tasks", "turns.coverage.tasks")
        + " · trace " + fig(format_percent(coverage.get("trace_rate")), "percent", "turns.coverage.trace_rate"),
    )
    excluded_bits = []
    for key, label in (
        ("excluded_no_edit", "no edit"),
        ("excluded_empty_trace", "empty trace"),
        ("excluded_no_detectable_edit", "no detectable edit"),
        ("excluded_no_invocation", "no invocation"),
        ("excluded_incomplete_trace", "incomplete trace"),
    ):
        if total.get(key) is None:
            continue
        excluded_bits.append(fig(unit_count(total.get(key), "tasks"), "tasks", f"turns.total.{key}") + " " + label)
    tier_cards = [headline, bytes_card, coverage_card]
    line_series = []
    for key in ("low", "medium", "hard", "xhard"):
        index = _series_index(series, key)
        if index is None:
            continue
        item = series[index]
        cell = item.get("total") or {}
        if cell.get("n"):
            tier_cards.append(score_card(
                TIER_LABEL.get(key, key),
                fig(format_turns(cell.get("mean_turns")), "turns", f"turns.series.{index}.total.mean_turns", cls="value"),
                fig(unit_count(cell.get("n"), "tasks"), "tasks", f"turns.series.{index}.total.n")
                + " · median " + fig(format_turns(cell.get("median_turns")), "turns", f"turns.series.{index}.total.median_turns"),
            ))
        line_series.append({
            "cls": f"s-{key}",
            "field": f"turns.series.{index}.points.mean_turns",
            "values": [chart_value((point or {}).get("mean_turns"), "turns") for point in item.get("points") or []],
        })
    chart = line_chart(
        [item for item in line_series if any(value is not None for value in item["values"])],
        "turns",
        "Mean turns to first edit each UTC day, by complexity",
        starts[0] if starts else None,
        starts[-1] if starts else None,
        "turns.bucket_starts.0",
        f"turns.bucket_starts.{len(starts) - 1}",
    ) if starts else ""
    providers = turns.get("available_providers") or []
    provider_rows = []
    for index, provider in enumerate(providers):
        tasks = (provider.get("coverage") or {}).get("tasks")
        provider_rows.append("".join([
            f"<th scope=\"row\">{text_fig(provider.get('provider'), f'turns.available_providers.{index}.provider')}</th>",
            "<td>" + fig(unit_count(tasks, "tasks"), "tasks", f"turns.available_providers.{index}.coverage.tasks") + "</td>",
        ]))
    intro_outcome = text_fig(turns.get("outcome"), "turns.outcome")
    intro = f"Turns until the first edit on tasks with outcome {intro_outcome}. Means use tasks with a measured edit. This is not the succeeded-run filter used for duration."
    body = "".join([
        board_window(window, "turns.window", metrics),
        turns_warning(coverage),
        cards(tier_cards),
        "<p class=\"detail\">" + " · ".join(excluded_bits) + "</p>" if excluded_bits else "",
        legend([(f"s-{key}", TIER_LABEL[key], "line") for key in ("low", "medium", "hard", "xhard")]),
        chart,
        more(f"Tasks by provider ({len(provider_rows)} providers)",
             table("Tasks in the turns window, by provider. Turn means above are pooled.", ["Provider", "Tasks"], provider_rows, preview=False)),
    ])
    return section("turns", "Turns to first edit", intro, body)


def section_outcome(metrics):
    mix = metrics.get("completion_by_complexity") or {}
    rows = mix.get("by_complexity") or []
    scope = fig(format_scope(mix.get("scope")), "scope", "completion_by_complexity.scope")
    plot_w = 280
    blocks = []
    for index, row in enumerate(rows):
        counts = {}
        status_index = {}
        for status_at, status in enumerate(row.get("statuses") or []):
            counts[status.get("status")] = status.get("count") or 0
            status_index[status.get("status")] = status_at
        total = row.get("total") or 0
        complexity = row.get("complexity")
        label = "unset (unlabeled)" if complexity == "unset" else TIER_LABEL.get(complexity, complexity)
        rects = []
        cursor = 0.0
        for key, cls in (("done", "s-low"), ("rejected", "s-hard"), ("archived", "s-other")):
            if key not in status_index:
                continue
            amount = float(counts.get(key) or 0)
            width = bar_width(amount, total, plot_w) if total else 0.0
            at = status_index[key]
            rects.append(
                f'<rect class="bar {cls}" data-field="completion_by_complexity.by_complexity.{index}.statuses.{at}.count" '
                f'data-total="completion_by_complexity.by_complexity.{index}.total" '
                f'x="{cursor:.2f}" y="2" width="{width:.2f}" height="12"></rect>'
            )
            cursor += width
        done_at = status_index.get("done")
        done_fig = ""
        if done_at is not None:
            done_field = f"completion_by_complexity.by_complexity.{index}.statuses.{done_at}.count"
            done_fig = fig(format_ratio(counts.get("done"), total), "ratio", done_field, base=f"completion_by_complexity.by_complexity.{index}.total")
            done_fig += " done · " + fig(unit_count(counts.get("done"), "tasks"), "tasks", done_field)
        blocks.append(
            "<div class=\"outcome\">"
            f"<div class=\"outcome-label\"><span>{e(label)}</span> "
            f"{text_fig(complexity, f'completion_by_complexity.by_complexity.{index}.complexity')}</div>"
            f'<svg class="outcome-plot" viewBox="0 0 {plot_w} 16" data-plot-w="{plot_w}" role="img" aria-label="Outcome shares">'
            + "".join(rects) + "</svg>"
            f"<p class=\"detail\">{done_fig} of "
            + fig(unit_count(total, "tasks"), "tasks", f"completion_by_complexity.by_complexity.{index}.total")
            + "</p></div>"
        )
    intro = f"Share of tasks that are done, by complexity. Scope {scope}. This mix is not limited to the metrics window."
    body = "".join([
        "<p class=\"window\">Scope " + scope + ".</p>",
        legend([("s-low", "Done", "bar"), ("s-hard", "Rejected", "bar"), ("s-other", "Archived", "bar")]),
        '<div class="outcomes">' + "".join(blocks) + "</div>",
    ])
    return section("outcomes", "Outcome by complexity", intro, body,
                   badge='<span class="scope-pill">All time, not the window above</span>')


def _tile(href, group, label, value_html, delta_html, sub_html):
    return (
        f'<li><a class="tile" href="#{e(href)}">'
        f'<span class="tile-head"><span class="tile-label">{e(label)}</span>'
        f'<span class="tile-group">{e(group)} <span aria-hidden="true">→</span></span></span>'
        f'<span class="tile-value">{value_html}</span>'
        f'<span class="tile-delta">{delta_html}</span>'
        f'<span class="tile-sub">{sub_html}</span></a></li>'
    )


def glance(metrics):
    """At-a-glance tiles. Every figure is a marked span; '*' marks a rate derived here."""
    tiles = []
    durations = metrics.get("durations") or {}
    cur = (durations.get("current") or {}).get("all") or {}
    prev = (durations.get("previous") or {}).get("all") or {}
    if cur:
        tiles.append(_tile(
            "duration", "Speed", "Duration",
            fig(format_ms(cur.get("avg")), "duration", "durations.current.all.avg"),
            delta_fig(cur.get("avg"), prev.get("avg"), "duration", "durations.current.all.avg", "durations.previous.all.avg") if prev else "",
            '<span class="label">p95</span> ' + fig(format_ms(cur.get("p95")), "duration", "durations.current.all.p95")
            + " · " + fig(unit_count(cur.get("n"), "runs"), "runs", "durations.current.all.n"),
        ))
    completions = metrics.get("completions") or {}
    done = (completions.get("current") or {}).get("done") or {}
    prev_done = (completions.get("previous") or {}).get("done") or {}
    if done:
        tiles.append(_tile(
            "completed", "Throughput", "Tasks done",
            fig(unit_count(done.get("total"), "tasks"), "tasks", "completions.current.done.total"),
            delta_fig(done.get("total"), prev_done.get("total"), "better", "completions.current.done.total", "completions.previous.done.total") if prev_done else "",
            fig(unit_count((completions.get("current") or {}).get("rejected"), "rejected"), "rejected", "completions.current.rejected")
            + " · " + fig(unit_count((completions.get("current") or {}).get("archived"), "archived"), "archived", "completions.current.archived"),
        ))
    defects = metrics.get("defects") or {}
    dcur = defects.get("current") or {}
    dprev = defects.get("previous") or {}
    if dcur:
        tiles.append(_tile(
            "defects", "Quality", "Defects",
            fig(unit_count(dcur.get("total"), "defects"), "defects", "defects.current.total"),
            delta_fig(dcur.get("total"), dprev.get("total"), "worse", "defects.current.total", "defects.previous.total") if dprev else "",
            fig(format_ratio((dcur.get("lineage") or {}).get("unattributed"), dcur.get("total")), "ratio",
                "defects.current.lineage.unattributed", base="defects.current.total") + " unattributed",
        ))
        rate_now = per_done(dcur.get("total"), done.get("total"))
        rate_prev = per_done(dprev.get("total"), prev_done.get("total"))
        if rate_now is not None:
            tiles.append(_tile(
                "defects", "Quality", "Defects per done task *",
                fig(format_per_done(dcur.get("total"), done.get("total")), "per-done", "defects.current.total",
                    base="completions.current.done.total"),
                from_delta(rate_now, rate_prev, "worse", fig(
                    format_per_done(dprev.get("total"), prev_done.get("total")), "per-done",
                    "defects.previous.total", base="completions.previous.done.total")) if rate_prev is not None else "",
                "defects filed ÷ tasks done",
            ))
    index, cost = _family(metrics, "cost")
    if cost is not None:
        total = cost.get("total") or {}
        previous = cost.get("previous") or {}
        tiles.append(_tile(
            "cost", "Spend", "Spend",
            _family_count(index, cost).replace(' class="value"', ""),
            delta_fig(total.get("count"), previous.get("count"), "worse", f"friction.families.{index}.total.count", f"friction.families.{index}.previous.count") if previous else "",
            "done tasks only",
        ))
        tiles.append(_tile(
            "cost", "Spend", "Cost per done task",
            fig(format_usd(total.get("rate")), "usd", f"friction.families.{index}.total.rate"),
            delta_fig(total.get("rate"), previous.get("rate"), "rate-worse", f"friction.families.{index}.total.rate", f"friction.families.{index}.previous.rate") if previous else "",
            "spend ÷ " + fig(unit_count(total.get("denominator"), "tasks"), "tasks", f"friction.families.{index}.total.denominator") + " done",
        ))
    index, final = _family(metrics, "final_recovery")
    if final is not None:
        total = final.get("total") or {}
        previous = final.get("previous") or {}
        tiles.append(_tile(
            "friction", "Quality", final.get("label") or "Final recoveries",
            fig(format_percent(total.get("rate")), "percent", f"friction.families.{index}.total.rate"),
            delta_fig(total.get("rate"), previous.get("rate"), "rate-worse", f"friction.families.{index}.total.rate", f"friction.families.{index}.previous.rate") if previous else "",
            "of done tasks · " + fig(unit_count(total.get("count"), final.get("unit") or "events"), "events", f"friction.families.{index}.total.count"),
        ))
    turns = metrics.get("turns") or {}
    ttotal = turns.get("total") or {}
    coverage = turns.get("coverage") or {}
    if ttotal:
        tiles.append(_tile(
            "turns", "Speed", "Turns to first edit",
            fig(format_turns(ttotal.get("mean_turns")), "turns", "turns.total.mean_turns"),
            '<span class="delta flat">no previous window</span>',
            fig(format_percent(coverage.get("measured_rate")), "percent", "turns.coverage.measured_rate") + " of done tasks measured",
        ))
    return (
        '<section class="glance" aria-labelledby="glance-title">'
        '<div class="glance-head"><h2 id="glance-title">At a glance</h2>'
        '<p class="glance-key"><span class="delta good">Blue</span> improved · <span class="delta bad">orange</span> got worse'
        ' · grey within five percent · * derived on this page</p></div>'
        f'<ul class="tiles">{"".join(tiles)}</ul></section>'
    )


def render_body(metrics, picker="", banner=""):
    durations = metrics.get("durations") or {}
    window = durations.get("window") or {}
    outcome = text_fig(metrics.get("outcome"), "outcome")
    statement = ""
    if window.get("since") and window.get("until"):
        statement = (
            '<p class="window window-statement">'
            + (text_fig(window["key"], "durations.window.key") + " window · " if window.get("key") else "")
            + stamp(window["since"], "durations.window.since") + " – " + stamp(window["until"], "durations.window.until")
            + "</p>"
        )
        if window.get("previous_since") and window.get("previous_until"):
            statement += (
                '<p class="window window-previous">Changes compare with the window before: '
                + stamp(window["previous_since"], "durations.window.previous_since") + " – "
                + stamp(window["previous_until"], "durations.window.previous_until") + ".</p>"
            )
    hero = (
        '<p class="eyebrow">Orbit metrics</p>'
        "<h1>Metrics</h1>"
        f"<p class=\"summary\">Duration, completions, defects, tokens, cost, diff size, friction and turns. "
        f"Duration outcome {outcome}.</p>"
        + statement
        + "<p class=\"detail\">Every board below uses this UTC window unless it prints its own; "
        "the outcome-by-complexity board is an all-time mix. "
        "The page is rendered from the committed snapshot and does not call Orbit.</p>"
    )
    boards = {
        "duration": section_duration,
        "turns": section_turns,
        "completed": section_completions,
        "outcomes": section_outcome,
        "defects": section_defects,
        "friction": section_friction,
        "cost": section_cost,
        "tokens": section_tokens,
        "diff": section_diff,
    }
    tabs = []
    groups = []
    for key, title, members in GROUPS:
        names = " · ".join(label for _anchor, label in members)
        tabs.append(
            f'<li><a href="#{key}" data-tab="{key}">{e(title)} <span class="tab-boards">{e(names)}</span></a></li>'
        )
        groups.append(
            f'<section class="metric-group" id="{key}" data-group="{key}" aria-labelledby="{key}-title">'
            f'<h2 id="{key}-title">{e(title)}</h2>'
            + "".join(boards[anchor](metrics) for anchor, _label in members)
            + "</section>"
        )
    tabs.append('<li hidden><a href="#metrics-all" data-tab="all">All boards</a></li>')
    nav = f'<nav class="group-nav" aria-label="Metric groups"><ul>{"".join(tabs)}</ul></nav>'
    caveats = (
        "<section id=\"caveats\"><h2>Notes</h2><ul>"
        "<li>Figures are aggregates of crews, models and complexities: counts, rates, durations, lines and cost. "
        "The page does not list individual tasks.</li>"
        "<li>Duration uses succeeded runs. Tokens and turns use done tasks. "
        "Completions and cost take no run-outcome query filter, but completions count tasks moved to done "
        "and cost covers spend for tasks that reached done. Other boards take no run-outcome query filter.</li>"
        "<li>* Derived on this page: defects per done task is defects filed in the window divided by tasks moved to done "
        "in the same window; its previous figure divides the previous window's defects by the previous window's done tasks. "
        "Cost per done task and event rates come from the snapshot itself.</li>"
        "<li>A change within five percent is shown grey. Blue and orange follow each metric's direction: "
        "fewer defects or a shorter duration is blue.</li>"
        "<li>Coverage and thin-sample warnings are computed from the snapshot: turns warns when fewer than half of tasks "
        "were measured; tokens warns when a tenth or more of tasks were left out; cost warns whenever any invocation was "
        "left out because the cost total carries no measured-invocation count to compare against; and a complexity tier "
        "warns when it has fewer than thirty runs.</li>"
        "<li>Dimmed model and crew rows are a small sample and are not ranked.</li>"
        "<li>Outcome by complexity is a separate all-time mix.</li>"
        "</ul></section>"
    )
    return (
        f'<article class="analytics metrics-page" id="metrics-all">{hero}{banner}{picker}'
        + glance(metrics)
        + nav
        + "".join(groups)
        + caveats
        + "</article>"
    )


def render_page(root, metrics, day, picker=None, banner="", archive_month=None, url=None):
    root = pathlib.Path(root)
    if picker is None:
        picker = picker_html(root / "data" / "analytics", "metrics", "metrics.json", archive_month)
    page_url = url or "https://constellation-works.com/analytics/metrics/"
    description = "30-day Orbit metrics: duration for succeeded runs; tokens and turns for done tasks; plus completions, defects, cost, diff size and friction."
    footer = f"""<footer>
  <div class="wrap">
    <span>&copy; 2026 Constellation Works</span>
    <span class="sp">
      <a href="/notes/">Notes</a>
      <a href="https://github.com/constellation-works">github.com/constellation-works</a>
    </span>
  </div>
</footer>
<script src="{asset(root, 'theme.js')}"></script>
<script src="{asset(root, 'analytics.js')}" defer></script>"""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Metrics — Constellation Works</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(page_url)}">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/brand/png/cw-favicon-180.png">
<meta property="og:title" content="Metrics — Constellation Works">
<meta property="og:description" content="{e(description)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{e(page_url)}">
<meta property="og:image" content="https://constellation-works.com/brand/png/cw-lockup-light-1520.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="{asset(root, 'notes.css')}">
<link rel="stylesheet" href="{asset(root, 'analytics.css')}">
<script src="{asset(root, 'theme-init.js')}"></script>
</head>
<body>
{HEADER}
<main class="wrap">
{render_body(metrics, picker, banner)}
</main>
{footer}
</body>
</html>
"""


def load_metrics(directory):
    path = pathlib.Path(directory) / "metrics.json"
    try:
        metrics = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"{path}: {exc}")
    if metrics.get("schema_version") != 1:
        sys.exit(f"{path}: schema_version {metrics.get('schema_version')!r} is not 1")
    window = (metrics.get("durations") or {}).get("window") or {}
    if not window.get("since") or not window.get("until"):
        sys.exit(f"{path}: durations.window has no UTC since/until")
    return metrics


def newest_metrics(root):
    base = pathlib.Path(root) / "data" / "analytics"
    if not base.is_dir():
        sys.exit(f"{base}: analytics snapshot directory is missing")
    days = sorted(
        path for path in base.iterdir()
        if path.is_dir() and DAY.fullmatch(path.name) and (path / "metrics.json").is_file()
    )
    if not days:
        sys.exit("build.py: no data/analytics/<YYYY-MM-DD>/metrics.json")
    return days[-1].name, load_metrics(days[-1])


def build(root):
    root = pathlib.Path(root)
    base = root / "data" / "analytics"
    day, metrics = newest_metrics(root)
    dest = root / "public" / "analytics" / "metrics"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    (dest / "index.html").write_text(render_page(root, metrics, day), encoding="utf-8")
    print(f"built metrics ({day}) -> {dest}")
    for entry in monthly_archive_entries(base, "metrics.json", "metrics"):
        archived = load_metrics(entry["directory"])
        month_dest = dest / entry["month"]
        month_dest.mkdir(parents=True)
        (month_dest / "index.html").write_text(
            render_page(
                root, archived, entry["date"],
                picker=picker_html(base, "metrics", "metrics.json", entry["month"]),
                banner=archive_banner("metrics", entry),
                archive_month=entry["month"],
                url=f"https://constellation-works.com/analytics/metrics/{entry['month']}/",
            ),
            encoding="utf-8",
        )
        print(f"built metrics archive {entry['month']} ({entry['date']}) -> {month_dest}")
