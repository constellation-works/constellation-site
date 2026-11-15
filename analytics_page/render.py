"""Glance tiles, page render and the metrics build entry point.

Moved unchanged from analytics_page.py.
"""

import json
import pathlib
import shutil
import sys

from .common import (
    ANALYTICS_CSS,
    DAY,
    GROUPS,
    HEADER,
    e,
)

from .archive import (
    monthly_archive_entries,
    archive_banner,
    picker_html,
)

from .present import (
    asset,
    format_ms,
    format_usd,
    format_turns,
    format_percent,
    format_ratio,
    per_done,
    format_per_done,
    unit_count,
    fig,
    text_fig,
    delta_fig,
    stamp,
)

from .sections import (
    section_duration,
    section_completions,
    section_defects,
    from_delta,
    section_tokens,
    _family,
    _family_count,
    section_cost,
    section_diff,
    section_friction,
    section_turns,
    section_outcome,
)

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
    stylesheets = "\n".join(f'<link rel="stylesheet" href="{asset(root, name)}">'
                            for name in ANALYTICS_CSS)
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
{stylesheets}
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
