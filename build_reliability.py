"""Reliability page (split from build.py)."""

import datetime
import html
import json
import math
import pathlib
import re
import shutil
import sys
import analytics_page
from build_common import DATE_DIR, ROOT, SITE, UTC_STAMP, _analytics_base, friendly_window, join_words, latest_analytics_dir, page, plural


RELIABILITY_OUTCOMES = (
    ("succeeded", "Succeeded"),
    ("failed", "Direct failures"),
    ("cascaded", "Cascaded failures"),
    ("cancelled", "Cancelled"),
    ("held", "Held"),
    ("upgrade_paused", "Paused for upgrade"),
    ("in_flight", "In flight"),
    ("skipped", "Skipped"),
    ("unknown", "Unknown outcome"),
)

def reliability_aggregates(data):
    """Project only known numeric fields and validated timestamps, never labels.

    In particular, source, activities, observed_states and arbitrary
    future diagnostic fields have no route into the public HTML.
    Per-job breakdowns use reliability_by_job, which validates job ids and
    recomputes rates from counts.
    """
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        sys.exit("reliability.json: expected schema_version 1")
    window = data.get("window")
    if not isinstance(window, dict) or window.get("label") != "30d":
        sys.exit("reliability.json: expected a 30d UTC window")
    stamps = [window.get(key) for key in ("since", "until")]
    if any(not isinstance(value, str) or not UTC_STAMP.fullmatch(value) for value in stamps):
        sys.exit("reliability.json: expected exact UTC since/until timestamps")
    try:
        since, until = [datetime.datetime.fromisoformat(value.replace("Z", "+00:00")) for value in stamps]
    except ValueError:
        sys.exit("reliability.json: invalid UTC timestamp")
    if until - since != datetime.timedelta(days=30):
        sys.exit("reliability.json: UTC window must span 30 days")
    totals = data.get("totals")
    runs = totals.get("job_runs") if isinstance(totals, dict) else None
    counts = runs.get("counts") if isinstance(runs, dict) else None
    keys = ("total",) + tuple(key for key, _label in RELIABILITY_OUTCOMES)
    if not isinstance(counts, dict) or any(type(counts.get(key)) is not int or counts[key] < 0 for key in keys):
        sys.exit("reliability.json: expected non-negative integer outcome counts")
    if counts["total"] != sum(counts[key] for key, _label in RELIABILITY_OUTCOMES):
        sys.exit("reliability.json: outcome counts do not add up to total")
    return {key: counts[key] for key in keys}, stamps

def reliability_table(rows, denominator, caption):
    """Rates are recomputed from counts; zero support never becomes 0% success."""
    rendered = []
    for label, count in rows:
        rate = f"{count / denominator:.2%}" if denominator else "Unavailable"
        rendered.append(
            f'<tr><td data-label="Outcome"><span class="value">{html.escape(label)}</span></td>'
            f'<td class="num" data-label="Count"><span class="value">{count:,} runs</span></td>'
            f'<td class="num" data-label="Rate"><span class="value">{rate}</span></td></tr>'
        )
    return (
        '<div class="table"><table>'
        f'<caption class="sr-only">{html.escape(caption)}</caption>'
        '<thead><tr><th scope="col">Outcome</th><th scope="col" class="num">Count (runs)</th>'
        '<th scope="col" class="num">Rate (%)</th></tr></thead>'
        f'<tbody>{"".join(rendered)}</tbody></table></div>'
    )

SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9_@.+-]{1,80}$")

JOB_LABELS = {
    "task_pr_pipeline": "PR delivery",
    "task_pilot_pipeline": "Pilot delivery",
    "ci_failure_sweep_pipeline": "CI failure sweep",
    "task_auto_pipeline": "Auto delivery",
    "task_landing_pipeline": "Landing",
    "agent_explore_pipeline": "Agent explore",
    "task_gate_pipeline": "Task gate",
    "escalation_triage_pipeline": "Escalation triage",
    "workspace_auto_pipeline": "Workspace auto",
    "ux_rules_pipeline": "UX rules",
    "image_input_probe_pipeline": "Image input probe",
    "task_local_pipeline": "Local delivery",
    "worktree_gc_pipeline": "Worktree GC",
    "blocked_task_recovery_pipeline": "Blocked task recovery",
    "finding_verification_pipeline": "Finding verification",
    "crew_performance_refresh_pipeline": "Crew performance refresh",
    "dependabot_alert_sweep_pipeline": "Dependabot sweep",
    "baseline_hold_refresh_pipeline": "Baseline hold refresh",
    "resident_cycle_pipeline": "Resident cycle",
    "store_gc_pipeline": "Store GC",
    "agent_invoke_pipeline": "Agent invoke",
    "workspace_pull_pipeline": "Workspace pull",
    "review_evidence_fulfilment_pipeline": "Review evidence",
    "task_publication_pipeline": "Task publication",
    "evolution_pass_pipeline": "Evolution pass",
    "orb20863_visual_eval": "Visual eval",
}

def job_label(job_id):
    """Human-readable name for a job id, falling back to the raw id."""
    return JOB_LABELS.get(job_id, job_id)

def reliability_by_job(data):
    """Validated per-job aggregates for the public page.

    Drops rows whose job id fails SAFE_JOB_ID or whose counts are not exact
    non-negative integers, recomputes each failure rate from counts (never the
    snapshot's supplied rate), keeps only the snapshot's boolean low_sample
    flag, and sorts by failures then total, as the snapshot orders them.
    """
    rows = data.get("by_job") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    jobs = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        job = row.get("job_id")
        if not isinstance(job, str) or not SAFE_JOB_ID.fullmatch(job):
            continue
        counts = row.get("counts")
        if not isinstance(counts, dict):
            continue
        valid = {}
        ok = True
        for key in ("succeeded", "failed", "total"):
            value = counts.get(key)
            if type(value) is not int or value < 0:
                ok = False
                break
            valid[key] = value
        if not ok:
            continue
        denominator = valid["succeeded"] + valid["failed"]
        rate = valid["failed"] / denominator if denominator else None
        supplied = row.get("failure_rate")
        low = isinstance(supplied, dict) and supplied.get("low_sample") is True
        jobs.append({
            "job_id": job,
            "label": JOB_LABELS.get(job, job),
            "succeeded": valid["succeeded"],
            "failed": valid["failed"],
            "total": valid["total"],
            "denominator": denominator,
            "rate": rate,
            "low": low,
        })
    jobs.sort(key=lambda job: (-job["failed"], -job["total"], job["job_id"]))
    return jobs

HOT_JOB_RATE = 0.05

SPIKE_MIN_RATE = 0.05

SPIKE_FACTOR = 1.5

MONTH_DAY = "%b"

def pct(part, whole, places=2):
    return f"{part / whole:.{places}%}" if whole else "Unavailable"

def short_pct(rate):
    """Two decimals under 1%, one above: 0.08%, 7.7%."""
    if rate is None:
        return "Unavailable"
    return f"{rate:.2%}" if rate < 0.01 else f"{rate:.1%}"

def reliability_recovery(data):
    """totals.recovery.per_job_run as (numerator, denominator), counts only."""
    totals = data.get("totals")
    recovery = totals.get("recovery") if isinstance(totals, dict) else None
    per_run = recovery.get("per_job_run") if isinstance(recovery, dict) else None
    if not isinstance(per_run, dict):
        return None
    numerator, denominator = per_run.get("numerator"), per_run.get("denominator")
    if type(numerator) is not int or type(denominator) is not int or numerator < 0 or denominator <= 0:
        return None
    if numerator > denominator:
        return None
    return numerator, denominator

def reliability_days(data, since, until):
    """Validated daily buckets from over_time, rates recomputed from counts.

    A bucket that starts before the window opens or ends after it closes is a
    partial day. Rows with a bad stamp or counts are dropped, never guessed.
    """
    rows = data.get("over_time") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    opened = analytics_page.parse_time(since)
    closed = analytics_page.parse_time(until)
    days = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        start, end = row.get("bucket_start"), row.get("bucket_end")
        if not isinstance(start, str) or not isinstance(end, str):
            continue
        if not UTC_STAMP.fullmatch(start) or not UTC_STAMP.fullmatch(end):
            continue
        try:
            begins, ends = analytics_page.parse_time(start), analytics_page.parse_time(end)
        except ValueError:
            continue
        if ends <= begins:
            continue
        counts = row.get("counts")
        if not isinstance(counts, dict):
            continue
        succeeded, failed = counts.get("succeeded"), counts.get("failed")
        if type(succeeded) is not int or type(failed) is not int or succeeded < 0 or failed < 0:
            continue
        settled = succeeded + failed
        days.append({
            "start": start,
            "begins": begins,
            "failed": failed,
            "settled": settled,
            "rate": failed / settled if settled else None,
            "partial": begins < opened or ends > closed,
        })
    days.sort(key=lambda day: day["begins"])
    return days

def day_label(day):
    return f"{day['begins'].day} {day['begins'].strftime(MONTH_DAY)}"

def daily_chart(days, overall_rate):
    """Failure rate per UTC day as HTML bars, with a 30-day reference line,
    a settled-runs strip, spike labels and a per-day text alternative."""
    e = html.escape
    rated = [day["rate"] for day in days if day["rate"] is not None]
    if not rated:
        return '<p class="empty">No daily buckets in this window.</p>'
    top = max(rated + ([overall_rate] if overall_rate is not None else []))
    # Headroom above the tallest bar for its spike label.
    scale = max(0.02, math.ceil(top * 1.15 * 100 / 2) * 2 / 100)
    volume_top = max(day["settled"] for day in days) or 1
    # Rounded to the precision the note prints, so 1.5 x 20% labels a 30% day.
    threshold = round(max(SPIKE_MIN_RATE, (overall_rate or 0) * SPIKE_FACTOR), 3)
    bars, volumes, ticks = [], [], []
    for index, day in enumerate(days):
        rate = day["rate"]
        label = day_label(day)
        partial = " (partial day)" if day["partial"] else ""
        if rate is None:
            text = f"{label}: unavailable, no settled runs{partial}"
        else:
            text = f"{label}: {rate:.2%} · {day['failed']:,} failed of {day['settled']:,} settled{partial}"
        spike = rate is not None and rate >= threshold
        height = 0 if rate is None else max(1.5, rate / scale * 100)
        state = (" is-partial" if day["partial"] else "") + (" is-spike" if spike else "")
        spike_label = f'<span class="day-label" aria-hidden="true">{short_pct(rate)}</span>' if spike else ""
        bars.append(
            f'<li class="day{state}" title="{e(text)}" style="--h:{height:.1f}%">'
            f'{spike_label}<span class="day-bar"></span><span class="sr-only">{e(text)}</span></li>'
        )
        volume = max(4.0, day["settled"] / volume_top * 100)
        volumes.append(f'<span class="{state.strip()}"><span style="height:{volume:.1f}%"></span></span>')
        tick = label if index % 5 == 0 or index == len(days) - 1 else ""
        ticks.append(f"<span>{e(tick)}</span>")
    reference = ""
    if overall_rate is not None:
        reference = (
            f'<span class="day-ref" aria-hidden="true" style="bottom:{min(100.0, overall_rate / scale * 100):.1f}%">'
            f'<span>{overall_rate:.2%}</span></span>'
        )
    peak = max(days, key=lambda day: (day["settled"], day["begins"]))
    partial_days = [day for day in days if day["partial"]]
    partial_note = (
        f" Faded: partial days ({join_words(day_label(day) for day in partial_days)}), where the window "
        "opens or closes mid-day." if partial_days else ""
    )
    table_rows = "".join(
        f'<tr><td data-label="Day"><time datetime="{e(day["start"])}">{e(day_label(day))}</time>'
        f'{" (partial)" if day["partial"] else ""}</td>'
        f'<td class="num" data-label="Failure rate">{e(pct(day["failed"], day["settled"]))}</td>'
        f'<td class="num" data-label="Failed">{day["failed"]:,}</td>'
        f'<td class="num" data-label="Settled runs">{day["settled"]:,}</td></tr>'
        for day in reversed(days)
    )
    table_html = (
        '<details class="more"><summary>Daily figures as a table</summary><div class="table"><table>'
        '<caption class="sr-only">Failure rate by UTC day, newest first</caption>'
        '<thead><tr><th scope="col">Day</th><th scope="col" class="num">Failure rate</th>'
        '<th scope="col" class="num">Failed</th><th scope="col" class="num">Settled runs</th></tr></thead>'
        f'<tbody>{table_rows}</tbody></table></div></details>'
    )
    return (
        '<div class="daychart-box"><div class="daychart-grid">'
        f'<div class="daychart-axis" aria-hidden="true"><span>{scale:.0%}</span><span>0%</span></div>'
        f'<div class="daychart-plot">{reference}'
        f'<ol class="daychart" aria-label="Failure rate by UTC day, oldest first">{"".join(bars)}</ol></div>'
        f'<div class="day-vols" aria-hidden="true">{"".join(volumes)}</div>'
        f'<div class="day-ticks" aria-hidden="true">{"".join(ticks)}</div></div>'
        f'<p class="daychart-note">Grey strip: settled runs per day (peak {peak["settled"]:,} on {e(day_label(peak))}). '
        f'Labelled bars are at least {threshold:.1%}.{e(partial_note)}</p>'
        f'</div>{table_html}'
    )

def reliability_by_job_section(jobs, total_failed):
    """Failures by job: bars by count or by rate, small samples marked."""
    e = html.escape
    failing = [job for job in jobs if job["failed"] > 0]
    clean = [job for job in jobs if job["failed"] == 0]
    head = (
        '<div class="board-head"><h2 id="by-job-title">Failures by job</h2>'
        '<div class="board-toggle job-sort" role="group" aria-label="Sort jobs" hidden>'
        '<button type="button" aria-pressed="true" data-sort="count">Most failures</button>'
        '<button type="button" aria-pressed="false" data-sort="rate">Highest rate</button></div></div>'
    )
    intro = (
        '<p class="score-key">Rate = direct failures ÷ settled runs (successes plus direct failures) for '
        "each job, all workspaces combined. The counts and percentages name the rate, not colour alone.</p>"
    )
    if not failing:
        return (
            f'<section class="board" id="by-job" aria-labelledby="by-job-title">{head}{intro}'
            '<p class="empty">No job failures in this window.</p>'
            + clean_jobs(clean) + "</section>"
        )
    max_failed = max(job["failed"] for job in failing)
    sized = [job["rate"] for job in failing if job["rate"] is not None and not job["low"]]
    max_rate = max(sized, default=None) or max((job["rate"] or 0 for job in failing), default=0) or 1
    rows = []
    for order, job in enumerate(failing):
        rate = job["rate"]
        hot = rate is not None and rate >= HOT_JOB_RATE and not job["low"]
        tag = "small sample" if job["low"] else (f"above {HOT_JOB_RATE:.0%}" if hot else "")
        w_count = max(0.5, job["failed"] / max_failed * 100)
        w_rate = max(0.5, min(100.0, (rate or 0) / max_rate * 100))
        tone = "is-low" if job["low"] else ("is-hot" if hot else "")
        rows.append(
            f'<tr class="job {tone}" data-order="{order}" data-failed="{job["failed"]}" '
            f'data-rate="{rate if rate is not None else -1:.6f}" data-low="{1 if job["low"] else 0}">'
            f'<th scope="row" data-label="Job"><span class="job-name">{e(job["label"])}</span>'
            f'<span class="job-tag">{e(tag)}</span></th>'
            f'<td class="bar-cell job-bar-cell" data-label="Bar"><span class="job-bar" aria-hidden="true">'
            f'<span class="job-fill" style="--w-count:{w_count:.1f}%;--w-rate:{w_rate:.1f}%"></span></span></td>'
            f'<td class="num job-rate" data-label="Rate">{e(short_pct(rate))}</td>'
            f'<td class="num" data-label="Failed">{job["failed"]:,}</td>'
            f'<td class="num" data-label="Settled runs">{job["denominator"]:,}</td></tr>'
        )
    top = failing[0]
    share = f" {e(top['label'])} accounts for {top['failed'] / total_failed:.0%} of all direct failures." if total_failed else ""
    notes = (
        f'<p class="board-note sort-note" data-sort-note="count">Sorted by failed runs.{share}</p>'
        '<p class="board-note sort-note" data-sort-note="rate" hidden>Sorted by failure rate. '
        "Small samples, as the snapshot flags them, sink to the bottom.</p>"
    )
    table_html = (
        '<div class="table"><table class="bar-table jobs" data-sort="count">'
        '<caption class="sr-only">Direct failures by job</caption>'
        '<thead><tr><th scope="col">Job</th><th scope="col"><span class="when-count">Failed runs</span>'
        '<span class="when-rate">Failure rate</span></th><th scope="col" class="num">Rate</th>'
        '<th scope="col" class="num">Failed</th><th scope="col" class="num">Settled runs</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )
    return (
        f'<section class="board" id="by-job" aria-labelledby="by-job-title">{head}{intro}{notes}'
        f"{table_html}{clean_jobs(clean)}</section>"
    )

def clean_jobs(clean):
    if not clean:
        return ""
    count = len(clean)
    items = " · ".join(
        f'{html.escape(job["label"])} ({job["denominator"]:,})' for job in clean
    )
    return (
        f'<details class="more"><summary>{count} {plural(count, "job")} with no failures</summary>'
        f'<p class="board-note">{items}</p><p class="board-note">Settled runs in brackets.</p></details>'
    )

OUTCOME_MIX = (
    ("succeeded", "Succeeded", "mix-ok", "Counted in the success rate"),
    ("failed", "Direct failures", "mix-fail", "Counted in the failure rate"),
    ("cascaded", "Cascaded failures", "mix-echo", "Echoes of a direct failure; not rated"),
    ("other", "Other outcomes", "mix-other", "Held, cancelled, paused, in flight; not rated"),
)

OTHER_KEYS = ("held", "cancelled", "upgrade_paused", "in_flight", "skipped", "unknown")

def render_reliability_page(data, snapshot_date, picker=None, banner="", archive_month=None, url=None, root=None):
    if picker is None:
        picker = analytics_page.picker_html(_analytics_base(root), "reliability", "reliability.json", archive_month)
    if not isinstance(snapshot_date, str) or not DATE_DIR.fullmatch(snapshot_date):
        sys.exit("reliability snapshot date must be YYYY-MM-DD")
    e = html.escape
    counts, (since, until) = reliability_aggregates(data)
    total = counts["total"]
    settled = counts["succeeded"] + counts["failed"]
    other = sum(counts[key] for key in OTHER_KEYS)
    rate = counts["failed"] / settled if settled else None
    outcomes = dict(RELIABILITY_OUTCOMES)

    headline = (
        '<div class="rel-hero"><span class="tile-head">Settled runs that succeeded</span>'
        f'<span class="rel-big">{e(pct(counts["succeeded"], settled))}</span>'
        f'<span class="rel-sub">{counts["succeeded"]:,} of {settled:,} · '
        f'<span class="is-worse">{counts["failed"]:,}</span> failed directly</span></div>'
    )
    recovery = reliability_recovery(data)
    if recovery:
        recovery_tile = (
            f'{e(pct(recovery[0], recovery[1], 1))}',
            f"{recovery[0]:,} of {recovery[1]:,} job runs with steps",
        )
    else:
        recovery_tile = ("Unavailable", "no recovery figures in this snapshot")
    other_parts = [
        f"{counts['held']:,} held", f"{counts['cancelled']:,} cancelled",
        f"{counts['upgrade_paused'] + counts['in_flight']:,} paused or in flight",
    ]
    if counts["skipped"]:
        other_parts.append(f"{counts['skipped']:,} skipped")
    if counts["unknown"]:
        other_parts.append(f"{counts['unknown']:,} unknown")
    tiles = (
        ("recovery", "Needed recovery", *recovery_tile),
        ("cascaded", "Cascaded echoes", f"{counts['cascaded']:,}", "rolled into their origin, not counted twice"),
        ("other-outcomes", "Other outcomes", f"{other:,}", " · ".join(other_parts)),
    )
    tile_html = "".join(
        f'<li id="{key}"><div class="tile"><span class="tile-head">{e(label)}</span>'
        f'<span class="tile-value">{e(value)}</span><span class="tile-sub">{e(sub)}</span></div></li>'
        for key, label, value, sub in tiles
    )
    hero = (
        f'<section class="rel-top" id="settled" aria-label="Success and failure">{headline}'
        f'<ul class="tiles rel-tiles">{tile_html}</ul></section>'
    )

    mix_counts = {"succeeded": counts["succeeded"], "failed": counts["failed"],
                  "cascaded": counts["cascaded"], "other": other}
    aria = ", ".join(f"{pct(mix_counts[key], total)} {label.lower()}" for key, label, _cls, _note in OUTCOME_MIX)
    segments = "".join(
        f'<span class="mix-seg {cls}" style="flex-grow:{mix_counts[key]}"></span>'
        for key, _label, cls, _note in OUTCOME_MIX if mix_counts[key]
    )
    legend = "".join(
        f'<li><i class="{cls}" aria-hidden="true"></i><span><strong>{e(label)}</strong> '
        f'<span class="mix-n">{mix_counts[key]:,} · {e(pct(mix_counts[key], total))}</span>'
        f'<span class="mix-note">{e(note)}</span></span></li>'
        for key, label, cls, note in OUTCOME_MIX
    )
    every = reliability_table([(outcomes[key], counts[key]) for key, _label in RELIABILITY_OUTCOMES], total,
                              "Every outcome as a share of all recorded runs")
    mix = (
        '<section class="board" id="failures" aria-labelledby="failures-title">'
        f'<div class="board-head"><h2 id="failures-title">Where every run ended</h2>'
        f'<p class="board-key">Share of all {total:,} recorded runs</p></div>'
        + (f'<div class="mix-bar" role="img" aria-label="{e(aria)}">{segments}</div>' if total else "")
        + f'<ul class="mix-legend">{legend}</ul>'
        + f'<details class="more"><summary>Every outcome count</summary>{every}</details></section>'
    )

    days = reliability_days(data, since, until)
    daily = (
        '<section class="board" id="daily" aria-labelledby="daily-title">'
        '<div class="board-head"><h2 id="daily-title">Failure rate by day</h2>'
        '<p class="board-key">Direct failures ÷ settled runs per UTC day'
        + (f' · <span class="k-ref" aria-hidden="true"></span> 30-day rate {rate:.2%}' if rate is not None else "")
        + ' · faded = partial day</p></div>'
        + daily_chart(days, rate) + "</section>"
    )

    by_job = reliability_by_job_section(reliability_by_job(data), counts["failed"])

    method = '''<details class="more method" id="method"><summary>How these are counted</summary><ul>
<li>Settled runs = successes plus direct failures. Failure rates use this denominator, recomputed on this page from the counts.</li>
<li>A cascaded failure is a wrapper job echoing a failure that started in another job. It is rolled into the original, so it is not counted twice.</li>
<li>Held, cancelled, paused-for-upgrade, in-flight, skipped and unknown runs are outside the success and failure rates.</li>
<li>Recovery: a job run where any step needed a recovery attempt, out of runs with a recorded step invocation.</li>
<li>Days are UTC. The first and last days are partial when the 30-day window opens or closes mid-day.</li>
<li>Counts are as of the snapshot. Held and in-flight runs can settle in later snapshots. Rates describe observed outcomes, not causes, and are not a comparison of crews.</li>
</ul></details>'''
    empty = '<p class="empty">No recorded runs in this window. Rates are unavailable.</p>' if not total else ""
    body = f'''<article class="analytics reliability-page">
<h1>Reliability</h1>
{banner}{picker}
<p class="summary">Success, failure and other outcomes across the fleet over 30 days, from the daily public snapshot.</p>
<p class="window window-statement">Last 30 days · {friendly_window(since, until)}</p>
<p class="as-of">All workspaces · Snapshot {snapshot_date} · {total:,} recorded runs; {settled:,} settled outcomes.</p>
<p class="board-window">Exact window: <time datetime="{e(since)}">{e(since)}</time> to <time datetime="{e(until)}">{e(until)}</time> UTC.</p>
{empty}{hero}
{mix}
{daily}
{by_job}
{method}
</article>'''
    return page(
        "Reliability — Constellation Works",
        "Aggregate Orbit success and failure counts and rates over 30 days.",
        url or f"{SITE}/analytics/reliability/", body, current="analytics",
        extra_css=analytics_page.ANALYTICS_CSS, extra_js=("analytics.js",),
    )

def _load_reliability(directory):
    try:
        return json.loads((pathlib.Path(directory) / "reliability.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        sys.exit("build.py: newest snapshot must contain valid reliability.json")

def build_reliability(root=None):
    base_root = pathlib.Path(root) if root is not None else ROOT
    directory = latest_analytics_dir(base_root)
    if directory is None:
        sys.exit("build.py: no data/analytics/<YYYY-MM-DD>/ snapshot to render")
    data = _load_reliability(directory)
    rendered = render_reliability_page(data, directory.name, root=base_root)
    dest = base_root / "public" / "analytics" / "reliability"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    (dest / "index.html").write_text(rendered, encoding="utf-8")
    print(f"built reliability -> {dest} from {directory.name}")
    for entry in analytics_page.monthly_archive_entries(_analytics_base(base_root), "reliability.json", "reliability"):
        month_dest = dest / entry["month"]
        month_dest.mkdir(parents=True)
        (month_dest / "index.html").write_text(
            render_reliability_page(
                _load_reliability(entry["directory"]), entry["date"],
                picker=analytics_page.picker_html(_analytics_base(base_root), "reliability", "reliability.json", entry["month"]),
                banner=analytics_page.archive_banner("reliability", entry),
                archive_month=entry["month"],
                url=f"{SITE}/analytics/reliability/{entry['month']}/",
                root=base_root,
            ),
            encoding="utf-8",
        )
        print(f"built reliability archive {entry['month']} -> {month_dest} from {entry['date']}")
