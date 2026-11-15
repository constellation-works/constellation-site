"""Public diagnostics and outcome-mix projections."""

import re

from .common import (
    COMPLETION_DONE,
    DEFECT_LINEAGES,
    DEFECT_ORIGINS,
    DIFF_MEASURES,
    FRICTION_FAMILIES,
    FRICTION_PARTS,
    SAFE_KEY,
    SAFE_LABEL,
    SAFE_TOKEN,
    TIMESTAMP,
    TOKEN_CELL,
    TURNS_CELL,
    TURNS_COVERAGE,
    is_gap_actor,
    is_gap_crew,
    is_gap_model,
    is_number,
    numeric_map,
    whole,
)


def trend_window(window):
    if not isinstance(window, dict):
        return None
    out = {}
    for key in ("key", "since", "until", "previous_since", "previous_until"):
        value = window.get(key)
        if isinstance(value, str) and (key == "key" or TIMESTAMP.fullmatch(value[:20] + "Z") or "T" in value):
            out[key] = value
        elif value is None and key in window:
            out[key] = None
    for key in ("bucket_seconds", "lead_buckets"):
        if isinstance(window.get(key), int) and not isinstance(window.get(key), bool):
            out[key] = window[key]
    return out


def duration_stats(obj):
    if obj is None:
        return None
    if not isinstance(obj, dict):
        return None
    out = {}
    for key in ("n", "avg", "p50", "p95"):
        if is_number(obj.get(key)):
            out[key] = obj[key]
    return out or None


def project_actor(row, dropped, board):
    if not isinstance(row, dict):
        return None
    actor = row.get("actor")
    if is_gap_actor(actor):
        dropped[board] += 1
        return None
    if not isinstance(actor, str) or not re.fullmatch(r"[A-Za-z0-9_@ .+/-]{1,120}", actor):
        return None
    projected = duration_stats(row) or {}
    projected["actor"] = actor
    if "previous_avg" in row and (row["previous_avg"] is None or is_number(row["previous_avg"])):
        projected["previous_avg"] = row["previous_avg"]
    trend = row.get("trend")
    if isinstance(trend, list) and all(item is None or is_number(item) for item in trend):
        projected["trend"] = trend
    return projected


def project_duration_series(obj):
    if not isinstance(obj, dict):
        return None
    out = {}
    for key in ("all", "low", "medium", "hard", "xhard", "unset"):
        if key in obj:
            out[key] = duration_stats(obj[key])
    return out


def project_durations(payload, dropped):
    buckets = []
    for bucket in payload.get("buckets") or []:
        if not isinstance(bucket, dict):
            continue
        item = {}
        if isinstance(bucket.get("start"), str):
            item["start"] = bucket["start"]
        if is_number(bucket.get("other_runs")):
            item["other_runs"] = bucket["other_runs"]
        for key in ("all", "low", "medium", "hard"):
            if key in bucket:
                item[key] = duration_stats(bucket[key])
        buckets.append(item)
    actors = []
    for row in payload.get("actors") or []:
        projected = project_actor(row, dropped, "metrics_durations")
        if projected is not None:
            actors.append(projected)
    by_complexity = []
    for group in payload.get("implement_one_by_complexity") or []:
        if not isinstance(group, dict):
            continue
        complexity = group.get("complexity")
        if not isinstance(complexity, str) or not SAFE_KEY.fullmatch(complexity):
            continue
        group_actors = []
        for row in group.get("actors") or []:
            projected = project_actor(row, dropped, "metrics_durations")
            if projected is not None:
                group_actors.append(projected)
        by_complexity.append({
            "actors": group_actors,
            "complexity": complexity,
            "n": whole(group.get("n")) or 0,
        })
    return {
        "actors": actors,
        "buckets": buckets,
        "current": project_duration_series(payload.get("current")),
        "implement_one_by_complexity": by_complexity,
        "outcome": "succeeded" if payload.get("outcome") == "succeeded" else None,
        "previous": project_duration_series(payload.get("previous")) if payload.get("previous") is not None else None,
        "source": "GET /api/diagnostics/implement_one?since=30d&outcome=succeeded",
        "truncated": bool(payload.get("truncated")),
        "window": trend_window(payload.get("window")),
    }


def project_completion_counts(obj):
    if not isinstance(obj, dict):
        return None
    done = obj.get("done") if isinstance(obj.get("done"), dict) else {}
    return {
        "archived": whole(obj.get("archived")) or 0,
        "done": {key: whole(done.get(key)) or 0 for key in COMPLETION_DONE},
        "rejected": whole(obj.get("rejected")) or 0,
    }


def project_completions(payload):
    def buckets(rows):
        out = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            item = project_completion_counts(row)
            if isinstance(row.get("start"), str):
                item["start"] = row["start"]
            out.append(item)
        return out

    return {
        "buckets": buckets(payload.get("buckets")),
        "current": project_completion_counts(payload.get("current")),
        "lead_buckets": [project_completion_counts(row) for row in payload.get("lead_buckets") or []],
        "previous": project_completion_counts(payload.get("previous")) if payload.get("previous") is not None else None,
        "previous_undated": project_completion_counts(payload.get("previous_undated"))
        if payload.get("previous_undated") is not None else None,
        "source": "GET /api/diagnostics/completions?since=30d",
        "undated": project_completion_counts(payload.get("undated")),
        "window": trend_window(payload.get("window")),
    }


def project_defect_counts(obj):
    if not isinstance(obj, dict):
        return None
    lineage = obj.get("lineage") if isinstance(obj.get("lineage"), dict) else {}
    origin = obj.get("origin") if isinstance(obj.get("origin"), dict) else {}
    return {
        "lineage": {key: whole(lineage.get(key)) or 0 for key in DEFECT_LINEAGES},
        "origin": {key: whole(origin.get(key)) or 0 for key in DEFECT_ORIGINS},
        "total": whole(obj.get("total")) or 0,
    }


def project_defects(payload):
    buckets = []
    for row in payload.get("buckets") or []:
        if not isinstance(row, dict):
            continue
        item = project_defect_counts(row)
        if isinstance(row.get("start"), str):
            item["start"] = row["start"]
        buckets.append(item)
    return {
        "buckets": buckets,
        "current": project_defect_counts(payload.get("current")),
        "lead_buckets": [project_defect_counts(row) for row in payload.get("lead_buckets") or []],
        "lineages": list(DEFECT_LINEAGES),
        "origins": list(DEFECT_ORIGINS),
        "previous": project_defect_counts(payload.get("previous")) if payload.get("previous") is not None else None,
        "source": "GET /api/diagnostics/defects?since=30d",
        "window": trend_window(payload.get("window")),
    }


def project_number_cell(obj, fields):
    if not isinstance(obj, dict):
        return None
    out = {}
    for key in fields:
        value = obj.get(key)
        if isinstance(value, bool) or value is None or is_number(value):
            if key in obj:
                out[key] = value
    return out


def project_token_series(series):
    if not isinstance(series, dict):
        return None
    complexity, cohort = series.get("complexity"), series.get("cohort")
    if not isinstance(complexity, str) or not SAFE_KEY.fullmatch(complexity):
        return None
    if cohort not in ("all", "with", "without"):
        return None
    return {
        "cohort": cohort,
        "complexity": complexity,
        "lead_points": [project_number_cell(point, TOKEN_CELL) for point in series.get("lead_points") or []],
        "points": [project_number_cell(point, TOKEN_CELL) for point in series.get("points") or []],
        "total": project_number_cell(series.get("total"), TOKEN_CELL),
    }


def project_tokens(payload, dropped):
    models = []
    for row in payload.get("available_models") or []:
        if not isinstance(row, dict):
            continue
        model, tasks = row.get("model"), row.get("tasks")
        if is_gap_model(model):
            dropped["metrics_tokens"] += 1
            continue
        if not isinstance(model, str) or not SAFE_TOKEN.fullmatch(model) or not is_number(tasks):
            continue
        models.append({"model": model, "tasks": tasks})
    return {
        "available_models": models,
        "bucket_starts": [item for item in payload.get("bucket_starts") or [] if isinstance(item, str)],
        "excluded_other_model": whole(payload.get("excluded_other_model")) or 0,
        "min_tasks": whole(payload.get("min_tasks")),
        "outcome": payload.get("outcome") if payload.get("outcome") in ("done", "all") else None,
        "scope": payload.get("scope") if payload.get("scope") in ("all", "implement") else None,
        "series": [item for item in (project_token_series(series) for series in payload.get("series") or []) if item],
        "source": "GET /api/diagnostics/task_tokens?since=30d&outcome=done&scope=all",
        "total": project_number_cell(payload.get("total"), TOKEN_CELL),
        "undated_tasks": whole(payload.get("undated_tasks")) or 0,
        "window": trend_window(payload.get("window")),
    }


def project_turns(payload):
    def series_of(series):
        if not isinstance(series, dict):
            return None
        complexity, cohort = series.get("complexity"), series.get("cohort")
        if not isinstance(complexity, str) or not SAFE_KEY.fullmatch(complexity):
            return None
        if cohort not in ("all", "with", "without"):
            return None
        return {
            "cohort": cohort,
            "complexity": complexity,
            "points": [project_number_cell(point, TURNS_CELL) for point in series.get("points") or []],
            "total": project_number_cell(series.get("total"), TURNS_CELL),
        }

    providers = []
    for row in payload.get("available_providers") or []:
        if not isinstance(row, dict):
            continue
        provider = row.get("provider")
        if not isinstance(provider, str) or not SAFE_TOKEN.fullmatch(provider):
            continue
        providers.append({
            "coverage": project_number_cell(row, TURNS_COVERAGE),
            "provider": provider,
        })
    return {
        "available_providers": providers,
        "bucket_starts": [item for item in payload.get("bucket_starts") or [] if isinstance(item, str)],
        "coverage": project_number_cell(payload.get("coverage"), TURNS_COVERAGE),
        "excluded_other_provider": whole(payload.get("excluded_other_provider")) or 0,
        "min_tasks": whole(payload.get("min_tasks")),
        "outcome": payload.get("outcome") if payload.get("outcome") in ("done", "all") else None,
        "series": [item for item in (series_of(series) for series in payload.get("series") or []) if item],
        "source": "GET /api/diagnostics/turns_to_edit?since=30d&outcome=done",
        "total": project_number_cell(payload.get("total"), TURNS_CELL),
        "truncated": bool(payload.get("truncated")),
        "undated_tasks": whole(payload.get("undated_tasks")) or 0,
        "window": trend_window(payload.get("window")),
    }


def project_diff_cell(obj):
    if not isinstance(obj, dict):
        return None
    return {
        "mean": numeric_map(obj.get("mean")) or {},
        "median": numeric_map(obj.get("median")) or {},
        "n": whole(obj.get("n")) or 0,
        "sum": numeric_map(obj.get("sum")) or {},
        "thin": bool(obj.get("thin")),
    }


def project_diff_series(series, dropped):
    if not isinstance(series, dict):
        return None
    key = series.get("key")
    names = [crew for crew in series.get("crews") or [] if isinstance(crew, str)]
    gap_names = [crew for crew in names if is_gap_crew(crew)]
    dropped["metrics_diff"] += len(gap_names)
    if is_gap_crew(key):
        dropped["metrics_diff"] += 1
        return None
    if not isinstance(key, str) or not SAFE_TOKEN.fullmatch(key):
        return None
    kept = [crew for crew in names if isinstance(crew, str) and SAFE_TOKEN.fullmatch(crew) and not is_gap_crew(crew)]
    return {
        "crews": kept,
        "key": key,
        "lead_points": [project_diff_cell(point) for point in series.get("lead_points") or []],
        "points": [project_diff_cell(point) for point in series.get("points") or []],
        "total": project_diff_cell(series.get("total")),
    }


def project_diff(payload, dropped):
    complexities = []
    for row in payload.get("available_complexities") or []:
        if not isinstance(row, dict):
            continue
        complexity, deliveries = row.get("complexity"), row.get("deliveries")
        if isinstance(complexity, str) and SAFE_KEY.fullmatch(complexity) and is_number(deliveries):
            complexities.append({"complexity": complexity, "deliveries": deliveries})
    return {
        "available_complexities": complexities,
        "bucket_starts": [item for item in payload.get("bucket_starts") or [] if isinstance(item, str)],
        "crews": [item for item in (project_diff_series(series, dropped) for series in payload.get("crews") or []) if item],
        "measures": [item for item in payload.get("measures") or [] if item in DIFF_MEASURES],
        "min_deliveries": whole(payload.get("min_deliveries")),
        "overall": project_diff_series(payload.get("overall"), dropped),
        "source": "GET /api/diagnostics/diff_stats?since=30d",
        "window": trend_window(payload.get("window")),
    }


def project_friction_cell(obj):
    if not isinstance(obj, dict):
        return None
    breakdown = obj.get("breakdown") if isinstance(obj.get("breakdown"), dict) else {}
    projected = {
        "breakdown": {key: breakdown[key] for key in FRICTION_PARTS if is_number(breakdown.get(key))},
        "count": obj.get("count") if is_number(obj.get("count")) else 0,
        "denominator": whole(obj.get("denominator")) or 0,
        "rate": obj.get("rate") if (obj.get("rate") is None or is_number(obj.get("rate"))) else None,
        "sparse": bool(obj.get("sparse")),
    }
    if is_number(obj.get("excluded_invocations")):
        projected["excluded_invocations"] = obj["excluded_invocations"]
    return projected


def project_friction(payload, dropped):
    families = []
    for family in payload.get("families") or []:
        if not isinstance(family, dict) or family.get("family") not in FRICTION_FAMILIES:
            continue
        label, unit = family.get("label"), family.get("unit")
        families.append({
            "family": family["family"],
            "filtered": bool(family.get("filtered")),
            "label": label if isinstance(label, str) and SAFE_LABEL.fullmatch(label) else family["family"],
            "points": [project_friction_cell(point) for point in family.get("points") or []],
            "previous": project_friction_cell(family.get("previous")) if family.get("previous") is not None else None,
            "task_scoped": bool(family.get("task_scoped")),
            "total": project_friction_cell(family.get("total")),
            "unit": unit if isinstance(unit, str) and SAFE_TOKEN.fullmatch(unit) else "events",
        })
    crews = []
    for row in payload.get("available_crews") or []:
        if not isinstance(row, dict):
            continue
        crew, tasks = row.get("crew"), row.get("tasks")
        if is_gap_crew(crew):
            dropped["metrics_friction"] += 1
            continue
        if isinstance(crew, str) and SAFE_TOKEN.fullmatch(crew) and is_number(tasks):
            crews.append({"crew": crew, "tasks": tasks})
    complexities = []
    for row in payload.get("available_complexities") or []:
        if not isinstance(row, dict):
            continue
        complexity, tasks = row.get("complexity"), row.get("tasks")
        if isinstance(complexity, str) and SAFE_KEY.fullmatch(complexity) and is_number(tasks):
            complexities.append({"complexity": complexity, "tasks": tasks})
    done = payload.get("done") if isinstance(payload.get("done"), dict) else {}

    def count_list(key):
        values = done.get(key)
        if isinstance(values, list) and all(is_number(item) for item in values):
            return values
        if is_number(values):
            return values
        return None

    return {
        "available_complexities": complexities,
        "available_crews": crews,
        "bucket_starts": [item for item in payload.get("bucket_starts") or [] if isinstance(item, str)],
        "done": {
            "points": count_list("points"),
            "previous": whole(done.get("previous")),
            "previous_undated": whole(done.get("previous_undated")),
            "total": whole(done.get("total")),
            "undated": whole(done.get("undated")),
            "unfiltered_points": count_list("unfiltered_points"),
            "unfiltered_total": whole(done.get("unfiltered_total")),
            "unfiltered_undated": whole(done.get("unfiltered_undated")),
        },
        "families": families,
        "min_done": whole(payload.get("min_done")),
        "source": (
            "GET /api/diagnostics/delivery_friction?since=30d"
            "&families=step_recovery,final_recovery,auto_fix,merge_conflict,failed_ci,cost"
        ),
        "window": trend_window(payload.get("window")),
    }


def project_outcome_mix(payload):
    rows = []
    for row in payload.get("by_complexity") or []:
        if not isinstance(row, dict):
            continue
        complexity = row.get("complexity")
        if not isinstance(complexity, str) or not SAFE_KEY.fullmatch(complexity):
            continue
        statuses = []
        for status in row.get("statuses") or []:
            if not isinstance(status, dict):
                continue
            name = status.get("status")
            if not isinstance(name, str) or not SAFE_KEY.fullmatch(name):
                continue
            statuses.append({
                "count": whole(status.get("count")) or 0,
                "rate": status.get("rate") if is_number(status.get("rate")) else None,
                "status": name,
                "total": whole(status.get("total")) or 0,
            })
        rows.append({
            "complexity": complexity,
            "statuses": statuses,
            "total": whole(row.get("total")) or 0,
        })
    return {
        "by_complexity": rows,
        "scope": "all_time",
        "source": "GET /api/tasks/completion-by-complexity",
    }
