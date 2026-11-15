"""Experiments page (split from build.py)."""

import datetime
import html
import json
import math
import pathlib
import shutil
import sys
import analytics_page
from build_common import ROOT, SITE, UTC_STAMP, _analytics_base, as_number, gap_identity, latest_analytics_dir, page, render_window


EXPERIMENT_METRICS = {
    "implement_tokens": ("Implementation tokens", "tokens"),
    "total_tokens": ("Total tokens", "tokens"),
    "cost_usd": ("Cost", "USD"),
    "lead_time": ("Lead time", "hours"),
    "implement_duration": ("Implementation duration", "minutes"),
    "turns_before_first_edit": ("Turns before first edit", "turns"),
    "result_bytes_before_first_edit": ("Results before first edit", "bytes"),
    "first_pass_acceptance": ("First-pass acceptance", "%"),
    "review_repairs": ("Review repairs", "repairs/task"),
    "step_recoveries": ("Step recoveries", "recoveries/task"),
    "final_recoveries": ("Final recoveries", "recoveries/task"),
    "failed_checks": ("Failed checks", "checks/task"),
    "merge_conflicts": ("Merge conflicts", "conflicts/task"),
    "delivery_done_rate": ("Delivery done rate", "%"),
    "escaped_regressions": ("Escaped regressions", "regressions/task"),
    "lines_changed": ("Lines changed", "lines"),
    "cost_per_line": ("Cost per line", "USD/line"),
    "lead_time_per_line": ("Lead time per line", "hours/line"),
}

def _compact(value, suffixes=("K", "M", "B")):
    a = abs(value)
    sign = "-" if value < 0 else ""
    if a >= 1e9:
        text = f"{a / 1e9:.1f}{suffixes[2]}"
    elif a >= 1e6:
        text = f"{a / 1e6:.1f}{suffixes[1]}"
    elif a >= 1e3:
        text = f"{a / 1e3:.1f}{suffixes[0]}"
    else:
        return _plain(value)
    if text.endswith(".0" + text[-1]):
        text = text[:-3] + text[-1]
    return sign + text

def _plain(value):
    if float(value).is_integer():
        return f"{int(value):,}"
    if abs(value) >= 100:
        return f"{value:,.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}".rstrip("0").rstrip(".")
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    if text not in ("0", "-0"):
        return text
    # A non-zero magnitude below 0.005 would collapse to a signed zero that
    # contradicts the better/worse verdict. Show significant figures instead,
    # preferring plain decimals for readability and falling back to g-style
    # for magnitudes too small for fixed notation.
    for decimals in (4, 6, 8, 10):
        candidate = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
        if candidate not in ("0", "-0", "", "-"):
            return candidate
    return f"{value:.4g}"

def _money_text(amount):
    """Fixed 2-decimal dollars, expanding precision when a non-zero amount
    would otherwise collapse to zero (mirrors the _plain signed-zero guard)."""
    if amount == 0:
        amount = 0
    text = f"{amount:,.2f}"
    if amount != 0 and float(text.replace(",", "")) == 0:
        for decimals in (4, 6, 8, 10):
            candidate = f"{amount:,.{decimals}f}".rstrip("0").rstrip(".")
            if candidate not in ("0", "-0", "", "-") and float(candidate.replace(",", "")) != 0:
                return candidate
        return f"{amount:.4g}"
    return text

def _money_line_text(amount):
    """Fixed 4-decimal dollars-per-line, expanding precision on collapse."""
    if amount == 0:
        amount = 0
    text = f"{amount:,.4f}"
    if amount != 0 and float(text.replace(",", "")) == 0:
        for decimals in (6, 8, 10):
            candidate = f"{amount:,.{decimals}f}".rstrip("0").rstrip(".")
            if candidate not in ("0", "-0", "", "-") and float(candidate.replace(",", "")) != 0:
                return candidate
        return f"{amount:.4g}"
    return text

def _points_text(points):
    """Fixed 1-decimal points, expanding precision on collapse."""
    if points == 0:
        points = 0
    text = f"{points:.1f}"
    if points != 0 and float(text) == 0:
        for decimals in (2, 3, 4, 6, 8, 10):
            candidate = f"{points:.{decimals}f}".rstrip("0").rstrip(".")
            if candidate not in ("0", "-0", "", "-") and float(candidate) != 0:
                return candidate
        return f"{points:.4g}"
    return text

def experiment_value(value, unit):
    if not as_number(value) or not math.isfinite(value):
        return "Unavailable"
    if value == 0:
        value = 0
    if unit == "%":
        return f"{_points_text(value * 100)}%"
    if unit == "USD":
        return f"${_money_text(value)}"
    if unit == "USD/line":
        return f"${_money_line_text(value)} / line"
    if unit == "tokens":
        return f"{_compact(value)} tokens"
    if unit == "bytes":
        a = abs(value)
        if a >= 1024 ** 2:
            return f"{value / 1024 ** 2:.1f} MB".replace(".0 MB", " MB")
        if a >= 1024:
            return f"{value / 1024:.1f} KB".replace(".0 KB", " KB")
        return f"{_plain(value)} B"
    if unit == "minutes":
        return f"{_plain(value)} min"
    if unit == "hours":
        return f"{_plain(value)} h"
    if unit == "hours/line":
        return f"{_plain(value)} h / line"
    return f"{_compact(value) if abs(value) >= 10000 else _plain(value)} {unit}".strip()

def experiment_interval(value, unit):
    if not isinstance(value, list) or len(value) != 2:
        return "Unavailable"
    if any(not as_number(v) or not math.isfinite(v) for v in value) or value[0] > value[1]:
        return "Unavailable"
    return f"{experiment_value(value[0], unit)} – {experiment_value(value[1], unit)}"

def _valid_interval(value):
    return (
        isinstance(value, list) and len(value) == 2
        and all(as_number(v) and math.isfinite(v) for v in value) and value[0] <= value[1]
    )

def _diff_category(metric):
    key = metric.get("metric")
    _, display = EXPERIMENT_METRICS.get(key, (key, metric.get("unit") or ""))
    snap = metric.get("unit")
    if key in ("delivery_done_rate", "first_pass_acceptance") or snap == "rate" or display == "%":
        return "rate", display
    if key == "cost_usd" or snap == "usd" or display == "USD":
        return "money", display
    if key == "cost_per_line" or display == "USD/line":
        return "money_line", display
    if key in ("implement_tokens", "total_tokens") or display == "tokens" or snap == "tokens":
        return "tokens", display
    if display == "bytes" or snap == "bytes":
        return "bytes", display
    if snap == "minutes" or display == "minutes":
        return "minutes", display
    if snap == "hours" or display == "hours":
        return "hours", display
    return "generic", display or (snap or "")

def experiment_difference(value, metric):
    """Signed, human-formatted difference versus control (snapshot-projected only)."""
    if not as_number(value) or not math.isfinite(value):
        return "not measured"
    category, display = _diff_category(metric)
    sign = "+" if value > 0 else "-" if value < 0 else ""
    a = abs(value)
    if category == "rate":
        return f"{sign}{_points_text(a * 100)} points"
    if category == "money":
        return f"{sign}${_money_text(a)}"
    if category == "money_line":
        return f"{sign}${_money_line_text(a)} / line"
    if category == "tokens":
        return f"{sign}{_compact(a)} tokens"
    if category == "bytes":
        return f"{sign}{experiment_value(a, 'bytes')}"
    if category == "minutes":
        return f"{sign}{_plain(a)} min"
    if category == "hours":
        return f"{sign}{_plain(a)} h"
    suffix = display if display not in ("%",) else ""
    return f"{sign}{_compact(a) if a >= 10000 else _plain(a)} {suffix}".strip()

def experiment_difference_interval(value, metric):
    if not _valid_interval(value):
        return "interval unavailable"
    return f"{experiment_difference(value[0], metric)} to {experiment_difference(value[1], metric)}"

def experiment_stamp(value):
    # Keep nanosecond precision from the snapshot, while normalizing the UTC suffix.
    if not isinstance(value, str):
        sys.exit("experiments.json: missing UTC observation window")
    value = value.removesuffix("+00:00") + "Z" if value.endswith("+00:00") else value
    if not UTC_STAMP.fullmatch(value):
        sys.exit("experiments.json: invalid UTC observation window")
    try:
        datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        sys.exit("experiments.json: invalid UTC observation window")
    return value

def experiment_count(value):
    return f"{value:,}" if type(value) is int and value >= 0 else "Unavailable"

def experiment_metric_table(metric, arms):
    """Only named aggregate outcomes are rendered; unknown fields are never dumped."""
    key = metric.get("metric")
    label, unit = EXPERIMENT_METRICS[key]
    outcomes = {row["arm"]: row for row in metric.get("arms", []) if isinstance(row, dict) and isinstance(row.get("arm"), str)}
    rows = []
    for arm in arms:
        outcome = outcomes.get(arm["name"], {})
        measured = as_number(outcome.get("n")) and outcome["n"] > 0
        cells = [("Arm", html.escape(arm["name"]))]
        for stat in ("mean", "median"):
            if stat == "median" and metric.get("kind") == "rate":
                continue
            value = experiment_value(outcome.get(stat), unit) if measured else "Unavailable"
            interval = experiment_interval(outcome.get(stat + "_interval"), unit) if measured else "Unavailable"
            cells.append((stat.title(), f'{value}<br><span class="unit">Interval: {interval}</span>'))
        support = (
            f'{experiment_count(outcome.get("n"))} measured tasks<br>'
            f'<span class="unit">{experiment_count(outcome.get("open"))} open tasks; '
            f'{experiment_count(outcome.get("unmeasured"))} unmeasured tasks</span>'
        )
        cells.append(("Support", support))
        rows.append("<tr>" + "".join(
            f'<td data-label="{heading}"><span class="value">{value}</span></td>'
            for heading, value in cells
        ) + "</tr>")
    columns = ["Arm", "Mean"] + ([] if metric.get("kind") == "rate" else ["Median"]) + ["Support"]
    qualifier = " (exploratory, not a decision metric)" if metric.get("exploratory") else ""
    headers = "".join(f'<th scope="col">{col}</th>' for col in columns)

    def render_rows(part, overflow):
        caption = (
            f'<caption class="sr-only">Additional arms for {label}</caption>'
            if overflow else f'<caption class="sr-only">{label}: per-arm outcomes and supplied intervals</caption>'
        )
        return (
            f'<div class="table"><table>{caption}<thead><tr>{headers}</tr></thead>'
            f'<tbody>{"".join(part)}</tbody></table></div>'
        )

    return f'<h4>{label}{qualifier}</h4>' + analytics_page.with_row_disclosure(rows, render_rows, "arms")

STATUS_LABEL = {
    "withheld": "Verdict withheld",
    "inconclusive": "Inconclusive",
    "collecting": "Collecting",
    "stopped-early": "Stopped early - no verdict",
}

STOPPED_EARLY_REASON = "Concluded before reaching the minimum sample; no verdict is available."

def _join_names(names):
    names = [name for name in names if name]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]

def _lower_first(text):
    return text[:1].lower() + text[1:] if text else text

def _reason_html(reason):
    """Readout reasons quote arm and metric names in backticks; render them as code."""
    parts = html.escape(reason).split("`")
    return "".join(f"<code>{part}</code>" if index % 2 else part for index, part in enumerate(parts))

def _finite(value):
    return as_number(value) and math.isfinite(value)

def experiment_short_question(experiment, arms, metrics):
    """A one-line question assembled from the readout's own fields.

    The full hypothesis stays on the page; this is only the arms, the primary
    metric and its direction, the population and the guardrails, worded as a question.
    """
    treatment = [arm["name"] for arm in arms if not arm.get("control")]
    key = experiment.get("primary_metric")
    if not treatment or key not in EXPERIMENT_METRICS:
        return None
    metric = next((m for m in metrics if m.get("metric") == key), {})
    verb = {"lower": "lower", "higher": "raise"}.get(metric.get("better"), "change")
    label = _lower_first(EXPERIMENT_METRICS[key][0])
    population = experiment.get("population") if isinstance(experiment.get("population"), dict) else {}
    tiers = [t for t in population.get("complexity") or [] if isinstance(t, str)]
    scope = f" on {_join_names(tiers)} tasks" if tiers else ""
    definition = experiment.get("guardrail_definition")
    guards = [
        _lower_first(EXPERIMENT_METRICS[name][0])
        for name in (definition if isinstance(definition, dict) else {})
        if name in EXPERIMENT_METRICS
    ]
    guard_text = f", within the {_join_names(guards)} guardrails" if guards else ""
    lead = "Do" if len(treatment) > 1 else "Does"
    return f"{lead} {_join_names(treatment)} {verb} {label}{scope} compared with control{guard_text}?"

def experiment_fidelity(arm, treatment_count, warning_kinds):
    """(own, n) for a treatment arm: tasks that ran on the arm's own crew.

    The snapshot names no assigned crew, so the own crew is the observed crew
    named like the arm. A single treatment arm with no crew of its name falls
    back to enrolled tasks minus the readout's recorded crew mismatches.
    Returns None when neither rule applies.
    """
    n = arm.get("n")
    if type(n) is not int or n < 0:
        return None
    if n == 0:
        return 0, 0
    for row in arm.get("crew_mix") or []:
        if isinstance(row, dict) and row.get("crew") == arm["name"] and type(row.get("tasks")) is int:
            return row["tasks"], n
    mismatch = (warning_kinds or {}).get("crew_mismatch") if isinstance(warning_kinds, dict) else None
    if treatment_count == 1 and type(mismatch) is int and 0 <= mismatch <= n:
        return n - mismatch, n
    return None

def _experiment_cell(metric, diff, domain_points=None):
    """Classify one arm's difference from control. Clear only when the interval excludes zero."""
    better = metric.get("better") if metric.get("better") in ("higher", "lower") else None
    overall = diff.get("overall") if isinstance(diff, dict) and isinstance(diff.get("overall"), dict) else {}
    estimate = overall.get("estimate")
    if not _finite(estimate):
        return {"measured": False}
    interval = overall.get("interval") if _valid_interval(overall.get("interval")) else None
    clear = bool(interval) and (interval[0] > 0 or interval[1] < 0)
    if estimate == 0:
        kind, tag = "same", "Same"
        clear = False
    elif better is None:
        kind, tag = "neutral", "Higher" if estimate > 0 else "Lower"
        clear = False
    else:
        good = estimate < 0 if better == "lower" else estimate > 0
        if clear:
            kind, tag = ("better", "Better") if good else ("worse", "Worse")
        else:
            kind, tag = ("lean-better", "Leans better") if good else ("lean-worse", "Leans worse")
    sign = -1 if better == "lower" else 1
    return {
        "measured": True,
        "estimate": estimate,
        "interval": interval,
        "clear": clear,
        "kind": kind,
        "tag": tag,
        "oriented": [sign * estimate] + ([sign * v for v in interval] if interval else []),
        "text": experiment_difference(estimate, metric),
        "interval_text": experiment_difference_interval(interval, metric) if interval else "no interval",
        "short": _drop_unit(experiment_difference(estimate, metric), metric),
        "short_interval": _drop_unit(experiment_difference_interval(interval, metric), metric) if interval else "no interval",
    }

def _drop_unit(text, metric):
    """Scorecard cells sit under a row that names the unit; keep only short unit marks."""
    _, display = EXPERIMENT_METRICS.get(metric.get("metric"), ("", ""))
    text = text.replace(" points", " pts")
    for unit in (" tokens", " lines") + ((" " + display,) if display and display not in ("USD", "%", "hours", "minutes") else ()):
        text = text.replace(unit, "")
    return text

def experiment_metric_cells(metric, treatment):
    diffs = {}
    for diff in metric.get("differences") or []:
        if isinstance(diff, dict) and isinstance(diff.get("arm"), str) and diff["arm"] not in diffs:
            diffs[diff["arm"]] = diff
    return [_experiment_cell(metric, diffs.get(name)) for name in treatment]

def _cell_html(cell, arm_name):
    e = html.escape
    if not cell["measured"]:
        return f'<td class="sc-cell is-unmeasured" data-label="{e(arm_name)}"><span class="sc-nm">Not measured</span></td>'
    return (
        f'<td class="sc-cell is-{cell["kind"]}" data-label="{e(arm_name)}">'
        f'<span class="sc-top"><span class="sc-value">{e(cell["short"])}</span>'
        f'<span class="sc-tag">{e(cell["tag"])}</span></span>'
        f'{cell["plot"]}'
        f'<span class="sc-iv">{e(cell["short_interval"])}</span>'
        f'<span class="sr-only">{e(arm_name)}: {e(cell["text"])} difference from control, {e(cell["interval_text"])}</span></td>'
    )

def _cell_plot(cell, domain):
    def pct(v):
        return 50 + (v / domain) * 44

    oriented = cell["oriented"]
    rng = ""
    if len(oriented) == 3:
        lo, hi = sorted(oriented[1:])
        rng = f'<span class="sc-range" style="left:{pct(lo):.2f}%;width:{max(pct(hi) - pct(lo), 0.5):.2f}%"></span>'
    return (
        '<span class="sc-plot" aria-hidden="true"><span class="sc-zero"></span>'
        f'{rng}<span class="sc-dot" style="left:{pct(oriented[0]):.2f}%"></span></span>'
    )

def experiment_scorecard(metrics, treatment, heads, primary_key, caption):
    """One metric × arm matrix. Returns (table_html, unmeasured_labels, signals)."""
    e = html.escape
    rows, unmeasured, signals = [], [], []
    for metric in metrics:
        key = metric["metric"]
        label, unit = EXPERIMENT_METRICS[key]
        cells = experiment_metric_cells(metric, treatment)
        if not any(cell["measured"] for cell in cells):
            unmeasured.append(label)
            continue
        domain = max((abs(v) for cell in cells if cell["measured"] for v in cell["oriented"]), default=0) or 1
        for cell in cells:
            if cell["measured"]:
                cell["plot"] = _cell_plot(cell, domain)
        for name, cell in zip(treatment, cells):
            if cell["measured"] and cell["clear"]:
                signals.append((name, label, unit, cell))
        is_primary = key == primary_key
        any_clear = any(cell["measured"] and cell["clear"] for cell in cells)
        badge = ' <span class="sc-primary">Primary</span>' if is_primary else ""
        exploratory = ' <span class="sc-sub">exploratory</span>' if metric.get("exploratory") else ""
        unit_text = "points" if unit == "%" else unit
        rows.append(
            f'<tr class="{"is-primary" if is_primary else ""}" data-clear="{1 if any_clear or is_primary else 0}">'
            f'<th scope="row"><span class="sc-metric">{e(label)}{badge}</span>'
            f'<span class="sc-sub">{e(unit_text)}{exploratory}</span></th>'
            + "".join(_cell_html(cell, name) for name, cell in zip(treatment, cells))
            + "</tr>"
        )
    if not rows:
        return "", unmeasured, signals
    head = (
        '<th scope="col"><span class="sc-axis">Metric <span aria-hidden="true">· ← worse · better →</span></span></th>'
        + "".join(heads)
    )
    table_html = (
        f'<div class="table sc-wrap"><table class="scorecard"><caption class="sr-only">{e(caption)}</caption>'
        f'<thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )
    return table_html, unmeasured, signals

def _status_pill(state, label):
    e = html.escape
    marker = "status-stop" if state == "stopped-early" else "status-dot"
    return f'<span class="status-pill status-{e(state or "unknown")}"><span class="{marker}" aria-hidden="true"></span>{e(label)}</span>'

def render_experiments_page(data, snapshot_date, picker=None, banner="", archive_month=None, url=None, root=None):
    if picker is None:
        picker = analytics_page.picker_html(_analytics_base(root), "experiments", "experiments.json", archive_month)
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        sys.exit("experiments.json: expected schema_version 1")
    if not isinstance(data.get("experiments"), list):
        sys.exit("experiments.json: expected experiments array")
    e = html.escape
    sections, cards = [], []
    for experiment in data["experiments"]:
        if not isinstance(experiment, dict) or experiment.get("status") != "concluded":
            continue
        # Only public, sanitized narrative fields from analytics_snapshot.py are used.
        name = experiment.get("name") or "Unnamed experiment"
        question = experiment.get("hypothesis") or "Question unavailable in this snapshot."
        since, until = (experiment_stamp(experiment.get(key)) for key in ("started_at", "as_of"))
        start, end = (datetime.datetime.fromisoformat(v.replace("Z", "+00:00")) for v in (since, until))
        if start > end:
            sys.exit("experiments.json: observation window ends before it starts")
        days = round((end - start).total_seconds() / 86400)
        anchor = f"experiment-{len(sections) + 1}"
        arms = [arm for arm in experiment.get("arms", []) if isinstance(arm, dict) and isinstance(arm.get("name"), str)]
        arm_names = {arm["name"] for arm in arms}
        control_names = {arm["name"] for arm in arms if arm.get("control")} or {"control"}
        treatment_arms = [arm for arm in arms if arm["name"] not in control_names]
        treatment = [arm["name"] for arm in treatment_arms]
        control = next((arm for arm in arms if arm["name"] in control_names), None)
        enrolled = sum(arm["n"] for arm in arms if type(arm.get("n")) is int and arm["n"] >= 0)
        warning_kinds = experiment.get("warning_kinds")

        verdict = experiment.get("verdict") or {}
        state = verdict.get("state") if isinstance(verdict.get("state"), str) else None
        verdict_text = verdict.get("label") or state or "Unavailable"
        # Every published experiment is concluded; a frozen collecting verdict
        # means it stopped before the sample threshold, rather than still running.
        display_state = "stopped-early" if state == "collecting" else state
        status = STATUS_LABEL.get(display_state, (state or "Concluded").replace("_", " ").capitalize())
        status_reason = STOPPED_EARLY_REASON if display_state == "stopped-early" else ""
        if status_reason:
            verdict_text = status
        chosen = experiment.get("concluded_arm")
        has_choice = isinstance(chosen, str) and chosen in arm_names
        choice = e(chosen) if has_choice else "None recorded"
        recommended = verdict.get("arm")
        recommendation = (
            f'<p class="readout-note">Statistical recommendation: {e(recommended)}.</p>'
            if isinstance(recommended, str) and recommended in arm_names else ""
        )
        reasons = [reason for reason in verdict.get("reasons", []) if isinstance(reason, str)]

        metrics = [metric for metric in experiment.get("metrics", []) if isinstance(metric, dict) and metric.get("metric") in EXPERIMENT_METRICS]
        primary = [metric for metric in metrics if metric["metric"] == experiment.get("primary_metric")]
        primary_ids = {id(m) for m in primary}
        guardrails = [m for m in metrics if id(m) not in primary_ids and not m.get("exploratory")]
        exploratory = [m for m in metrics if id(m) not in primary_ids and m.get("exploratory")]
        primary_key = experiment.get("primary_metric")
        primary_label = EXPERIMENT_METRICS[primary_key][0] if primary_key in EXPERIMENT_METRICS else "Unavailable"

        heads = []
        fidelity = {}
        for arm in treatment_arms:
            fid = experiment_fidelity(arm, len(treatment_arms), warning_kinds)
            fidelity[arm["name"]] = fid
            tags = []
            if arm.get("retired_segment") is not None:
                tags.append("retired")
            if arm.get("drifted"):
                tags.append("drifted")
            tag_html = "".join(f' <span class="sc-flag">{t}</span>' for t in tags)
            sub = f"n={experiment_count(arm.get('n'))}"
            if fid and fid[1]:
                sub += f" · {fid[0]:,}/{fid[1]:,} on own crew"
            heads.append(
                f'<th scope="col"><span class="sc-arm">{e(arm["name"])}</span>{tag_html}'
                f'<span class="sc-sub">{e(sub)}</span></th>'
            )
        control_note = f"control n={experiment_count(control.get('n'))}" if control else "no control arm"

        decision_table, unmeasured, signals = experiment_scorecard(
            primary + guardrails, treatment, heads, primary_key,
            f"{name}: difference from control by metric and arm",
        )
        explore_table, explore_unmeasured, _ = experiment_scorecard(
            exploratory, treatment, heads, primary_key,
            f"{name}: exploratory metrics, difference from control",
        )
        better_n = sum(1 for _n, _l, _u, cell in signals if cell["kind"] == "better")
        worse_n = sum(1 for _n, _l, _u, cell in signals if cell["kind"] == "worse")

        if decision_table:
            matrix = decision_table
        else:
            empty = " ".join(
                f"{arm['name']} has {experiment_count(arm.get('n'))} enrolled tasks." for arm in treatment_arms
            )
            matrix = f'<p class="empty sc-empty">No treatment results yet. {e(empty)}</p>'
        nm_line = (
            f'<p class="sc-nm-line">Not measured for any arm: {e(", ".join(unmeasured))}.</p>'
            if unmeasured and decision_table else ""
        )
        if signals:
            items = "".join(
                f'<li class="signal is-{cell["kind"]}"><span class="signal-head"><span class="signal-arm">{e(arm)}</span>'
                f'<span class="signal-tag">{e(cell["tag"])}</span></span>'
                f'<span class="signal-metric">{e(label)}</span>'
                f'<span class="signal-value">{e(cell["short"])} <span class="unit">{e("points" if unit == "%" else unit)}</span></span>'
                f'<span class="signal-iv">{e(cell["short_interval"])}</span>'
                f'<span class="sr-only">{e(arm)}: {e(cell["text"])} difference from control, {e(cell["interval_text"])}</span></li>'
                for arm, label, unit, cell in signals
            )
            signals_html = f'<ul class="signals">{items}</ul>'
        else:
            signals_html = '<p class="empty">No decision metric has an interval that excludes zero yet.</p>'

        other_html = ""
        if exploratory:
            explore_nm = (
                f'<p class="sc-nm-line">Not measured for any arm: {e(", ".join(explore_unmeasured))}.</p>'
                if explore_unmeasured and explore_table else ""
            )
            other_html = (
                f'<details class="diff-exploratory"><summary>Other metrics ({len(exploratory)})</summary>'
                '<p class="board-note">Exploratory metrics: recorded for context, not decision metrics.</p>'
                + (explore_table or '<p class="empty">Not measured for any arm.</p>') + explore_nm + '</details>'
            )
        raw_html = (
            '<details class="experiment-raw"><summary>Raw per-arm outcomes</summary>'
            + "".join(experiment_metric_table(metric, arms) for metric in metrics) + '</details>'
        ) if metrics else ""

        arm_rows = []
        for arm in arms:
            crews = "".join(
                f'<span class="crew-chip">{e(row["crew"])} <span class="unit">{experiment_count(row.get("tasks"))}</span></span>'
                for row in arm.get("crew_mix", [])
                if isinstance(row, dict) and isinstance(row.get("crew"), str)
                and not gap_identity(row["crew"], row.get("model"))
            ) or '<span class="unit">None observed</span>'
            flags = [label for key, label in (("control", "control"), ("drifted", "drifted")) if arm.get(key)]
            if arm.get("retired_segment") is not None:
                flags.append("retired")
            flag_html = "".join(f' <span class="sc-flag">{f}</span>' for f in flags)
            if arm["name"] in control_names:
                fid_html = '<span class="unit">Reference arm</span>'
            else:
                fid = fidelity.get(arm["name"])
                if fid is None:
                    fid_html = '<span class="unit">Not recorded</span>'
                elif fid[1] == 0:
                    fid_html = '<span class="unit">No tasks yet</span>'
                else:
                    share = fid[0] / fid[1] * 100
                    fid_html = (
                        f'<span class="fid"><span class="fid-bar" aria-hidden="true"><span style="width:{share:.0f}%"></span></span>'
                        f'<span class="fid-text">{fid[0]:,} / {fid[1]:,}</span></span>'
                    )
            arm_rows.append(
                f'<tr><th scope="row"><span class="arm-name">{e(arm["name"])}</span>{flag_html}</th>'
                f'<td data-label="Enrolled">{experiment_count(arm.get("n"))}</td>'
                f'<td data-label="Ran on its own crew">{fid_html}</td>'
                f'<td data-label="Observed crews"><span class="crew-chips">{crews}</span></td></tr>'
            )
        arms_table = (
            '<div class="table"><table class="arms-table"><caption class="sr-only">Arms, enrolment and treatment delivery</caption>'
            '<thead><tr><th scope="col">Arm</th><th scope="col">Enrolled</th><th scope="col">Ran on its own crew</th>'
            '<th scope="col">Observed crews</th></tr></thead><tbody>' + "".join(arm_rows) + '</tbody></table></div>'
        )

        short = experiment_short_question(experiment, arms, metrics)
        question_html = (
            f'<p class="question-short">{e(short)}</p>'
            f'<details class="question-full"><summary>Full question and design</summary><p class="question">{e(question)}</p></details>'
            if short else f'<p class="question">{e(question)}</p>'
        )
        why_title = "Readout notes" if has_choice else "Why no decision"
        why_body = (
            "<ul>" + "".join(f"<li>{_reason_html(reason)}</li>" for reason in reasons) + "</ul>"
            if reasons else '<p class="empty">The readout records no reasons.</p>'
        )
        arm_word = "treatment arm" if len(treatment) == 1 else "treatment arms"
        day_word = "day" if days == 1 else "days"
        cards.append(
            f'<li><a class="exp-card" href="#{anchor}" data-exp="{anchor}">'
            f'<span class="exp-card-head"><span class="exp-card-name">{e(name)}</span>{_status_pill(display_state, status)}</span>'
            + (f'<span class="exp-card-reason">{e(status_reason)}</span>' if status_reason else "")
            + f'<span class="exp-card-q">{e(short or question)}</span>'
            f'<span class="exp-card-meta"><span>{len(treatment)} {arm_word}</span><span>{enrolled:,} tasks</span><span>{days} {day_word}</span></span>'
            f'<span class="exp-card-signals"><span class="is-better">{better_n} clear better</span>'
            f'<span aria-hidden="true">·</span><span class="is-worse">{worse_n} clear worse</span></span></a></li>'
        )
        sections.append(f'''<section class="board experiment" id="{anchor}" data-exp-section>
<div class="exp-head"><h2>{e(name)}</h2>{_status_pill(display_state, status)}</div>
{render_window(since, until)}
<p class="board-note">Cumulative observations from experiment start to readout ({days} {day_word}), not a rolling 30-day window.</p>
<dl class="readout">
<div><dt>Verdict</dt><dd>{e(verdict_text)}</dd></div>
<div><dt>Chosen arm</dt><dd>{choice}</dd></div>
<div><dt>Primary metric</dt><dd>{e(primary_label)}</dd></div>
<div><dt>Enrolled</dt><dd>{enrolled:,} tasks</dd></div>
</dl>
{f'<p class="readout-note">{e(status_reason)}</p>' if status_reason else ''}
{recommendation}
<div class="exp-split">
<div class="exp-question"><h3>Question</h3>{question_html}</div>
<div class="exp-why"><h3>{why_title}</h3>{why_body}</div>
</div>
<h3>Clear signals <span class="h-note">· interval excludes zero</span></h3>
{signals_html}
<div class="sc-head"><h3>Difference from control <span class="h-note">· {e(control_note)}</span></h3>
<div class="sc-tools"><ul class="sc-legend"><li><i class="k-better"></i>Better</li><li><i class="k-worse"></i>Worse</li><li><i class="k-lean"></i>Leans (interval crosses zero)</li></ul>
<button type="button" class="sc-filter" aria-pressed="false" hidden>Clear signals only</button></div></div>
{matrix}
{nm_line}
{other_html}{raw_html}
<h3>Arms and treatment delivery</h3>
{arms_table}
</section>''')
    method = '''<section class="exp-method" id="method"><details><summary>Method and caveats</summary><ul>
<li>Concluded is a lifecycle state, not proof of a winner. A verdict may be withheld or inconclusive. An experiment stopped before reaching the minimum sample has no verdict, and a chosen arm may be absent.</li>
<li>A cell is shaded only when its interval excludes zero. Every other cell is a direction, not a result. Intervals are copied from the readout; unavailable values are not zero.</li>
<li>Each cell is the treatment arm minus control. The plot runs worse to the left and better to the right, using each metric's own direction.</li>
<li>Support is specific to each metric; open regression windows can leave outcomes unsettled.</li>
<li>Windows are cumulative from experiment start to readout, not a rolling 30-day window.</li>
<li>"Ran on its own crew" counts tasks on the observed crew named like the arm; for a single treatment arm with no such crew it is enrolled tasks minus the readout's recorded crew mismatches.</li>
<li>The short question is assembled from the readout's arms, primary metric, population and guardrails; the full question is the experiment's own text.</li>
<li>These are experiment outcomes, not ranked crew scorecards. See the <a href="/notes/crew-rankings-method/">method note</a>.</li>
</ul></details></section>'''
    picker_cards = f'<nav class="exp-picker" aria-label="Choose an experiment"><ul>{"".join(cards)}</ul></nav>' if cards else ""
    body = f'''<article class="analytics experiments">
<h1>Concluded experiments</h1>
{banner}{picker}
<p class="summary">Questions, per-arm outcomes and decisions from Orbit's concluded experiments.</p>
<p class="as-of">Snapshot {e(snapshot_date)}. Built from the committed daily snapshot; no live Orbit calls.</p>
<p class="board-note">Concluded does not mean a winner. Only shaded cells have an interval that excludes zero; everything else is a direction, not a result. <a href="#method">Method and caveats</a>.</p>
{picker_cards}
{''.join(sections) if sections else '<p class="empty">No concluded experiments in this snapshot.</p>'}
{method if sections else ''}
</article>'''
    return page(
        "Concluded experiments — Constellation Works",
        "Questions, arms, aggregate outcomes, intervals and decisions from concluded Orbit experiments.",
        url or f"{SITE}/analytics/experiments/", body, current="analytics",
        extra_css=analytics_page.ANALYTICS_CSS, extra_js=("analytics.js",),
    )

def _load_experiments(directory):
    try:
        return json.loads((pathlib.Path(directory) / "experiments.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        sys.exit("build.py: newest snapshot must contain valid experiments.json")

def build_experiments(root=None):
    base_root = pathlib.Path(root) if root is not None else ROOT
    directory = latest_analytics_dir(base_root)
    if directory is None:
        sys.exit("build.py: no data/analytics/<YYYY-MM-DD>/ snapshot to render")
    data = _load_experiments(directory)
    rendered = render_experiments_page(data, directory.name, root=base_root)
    dest = base_root / "public" / "analytics" / "experiments"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    (dest / "index.html").write_text(rendered, encoding="utf-8")
    print(f"built experiments -> {dest} from {directory.name}")
    for entry in analytics_page.monthly_archive_entries(_analytics_base(base_root), "experiments.json", "experiments"):
        month_dest = dest / entry["month"]
        month_dest.mkdir(parents=True)
        (month_dest / "index.html").write_text(
            render_experiments_page(
                _load_experiments(entry["directory"]), entry["date"],
                picker=analytics_page.picker_html(_analytics_base(base_root), "experiments", "experiments.json", entry["month"]),
                banner=analytics_page.archive_banner("experiments", entry),
                archive_month=entry["month"],
                url=f"{SITE}/analytics/experiments/{entry['month']}/",
                root=base_root,
            ),
            encoding="utf-8",
        )
        print(f"built experiments archive {entry['month']} -> {month_dest} from {entry['date']}")
