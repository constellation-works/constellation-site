"""Snapshot directory lookup and the monthly archive picker.

Moved unchanged from analytics_page.py.
"""

import datetime
import json
import pathlib
import re

from .common import (
    DAY,
    e,
)

from .present import (
    parse_time,
)

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
