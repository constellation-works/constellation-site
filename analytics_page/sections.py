"""Metrics page sections.

Moved unchanged from analytics_page.py.
"""

from .common import (
    LOW_ACTOR_SAMPLE,
    TIER_LABEL,
    DURATION_LINES,
    VOLUME_STACK,
    DONE_STACK,
    LINEAGE,
    ORIGIN_LABEL,
    MEASURE_LABEL,
    PART_LABEL,
    TOKEN_TIERS,
    THIN_TIER_RUNS,
    COVERAGE_WARN_RATE,
    EVENT_FAMILIES,
    e,
)

from .present import (
    format_ms,
    format_usd,
    format_lines,
    format_turns,
    format_percent,
    format_ratio,
    format_share,
    per_done,
    format_per_done,
    format_scope,
    delta_class,
    unit_count,
    fig,
    text_fig,
    delta_fig,
    day_cell,
    nice_ceiling,
    chart_value,
    bar_width,
    line_chart,
    stack_chart,
    legend,
    sparkline,
    table,
    score_card,
    cards,
    section,
    more,
    warn,
    board_window,
    bucket_stat,
)

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
