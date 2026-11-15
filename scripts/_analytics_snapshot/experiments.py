"""Concluded experiment projections."""

import collections

from .common import (
    SAFE_ID,
    SAFE_KEY,
    SAFE_LABEL,
    SAFE_TOKEN,
    SCHEMA_VERSION,
    experiment_omitted,
    is_gap_crew,
    is_gap_model,
    is_number,
    number_list,
    numeric_map,
    project_usage,
    whole,
)
from .redaction import (
    sanitize,
)


def project_interval_arm(arm):
    if not isinstance(arm, dict):
        return None
    name = arm.get("arm")
    if not isinstance(name, str) or not SAFE_TOKEN.fullmatch(name):
        return None
    projected = {"arm": name}
    for key in ("mean", "median", "n", "open", "unmeasured"):
        value = arm.get(key)
        if value is None or is_number(value):
            if key in arm:
                projected[key] = value
    for key in ("mean_interval", "median_interval"):
        interval = number_list(arm.get(key), 2)
        if interval is not None:
            projected[key] = interval
    segments = []
    for segment in arm.get("segments") or []:
        if not isinstance(segment, dict) or not is_number(segment.get("segment")):
            continue
        item = {"n": whole(segment.get("n")) or 0, "segment": segment["segment"]}
        for key in ("mean", "median"):
            if is_number(segment.get(key)):
                item[key] = segment[key]
        for key in ("mean_interval", "median_interval"):
            interval = number_list(segment.get(key), 2)
            if interval is not None:
                item[key] = interval
        segments.append(item)
    if segments:
        projected["segments"] = segments
    return projected


def project_difference(diff):
    if not isinstance(diff, dict):
        return None
    name = diff.get("arm")
    if not isinstance(name, str) or not SAFE_TOKEN.fullmatch(name):
        return None
    overall = diff.get("overall") if isinstance(diff.get("overall"), dict) else {}
    dropped = overall.get("cells_dropped")
    cells = [item for item in dropped or [] if isinstance(item, str) and SAFE_KEY.fullmatch(item)] if isinstance(dropped, list) else []
    by_complexity = []
    for row in diff.get("by_complexity") or []:
        if not isinstance(row, dict):
            continue
        complexity = row.get("complexity")
        if not isinstance(complexity, str) or not SAFE_KEY.fullmatch(complexity):
            continue
        item = {
            "complexity": complexity,
            "estimate": row.get("estimate") if row.get("estimate") is None or is_number(row.get("estimate")) else None,
            "n_arm": whole(row.get("n_arm")) or 0,
            "n_control": whole(row.get("n_control")) or 0,
        }
        interval = number_list(row.get("interval"), 2)
        if interval is not None:
            item["interval"] = interval
        by_complexity.append(item)
    projected_overall = {
        "cells_dropped": cells,
        "estimate": overall.get("estimate") if overall.get("estimate") is None or is_number(overall.get("estimate")) else None,
    }
    interval = number_list(overall.get("interval"), 2)
    if interval is not None:
        projected_overall["interval"] = interval
    return {"arm": name, "by_complexity": by_complexity, "overall": projected_overall}


def project_metric(metric):
    if not isinstance(metric, dict):
        return None
    name = metric.get("metric")
    if not isinstance(name, str) or not SAFE_TOKEN.fullmatch(name):
        return None
    return {
        "arms": [item for item in (project_interval_arm(arm) for arm in metric.get("arms") or []) if item],
        "better": metric.get("better") if isinstance(metric.get("better"), str) and SAFE_TOKEN.fullmatch(metric["better"]) else None,
        "differences": [item for item in (project_difference(diff) for diff in metric.get("differences") or []) if item],
        "exploratory": bool(metric.get("exploratory")),
        "kind": metric.get("kind") if isinstance(metric.get("kind"), str) and SAFE_KEY.fullmatch(metric["kind"]) else None,
        "measured": bool(metric.get("measured")),
        "metric": name,
        "unit": metric.get("unit") if isinstance(metric.get("unit"), str) and SAFE_LABEL.fullmatch(metric["unit"]) else None,
    }


def project_experiment(definition, readout, dropped, patterns, redactions):
    if not isinstance(definition, dict):
        return None
    if experiment_omitted(definition) or definition.get("status") != "concluded":
        dropped["experiments_omitted"] += 1
        return None
    if not isinstance(readout, dict):
        return None
    if readout.get("experiment", {}).get("status") not in (None, "concluded"):
        dropped["experiments_omitted"] += 1
        return None
    ident = definition.get("id")
    if not isinstance(ident, str) or not SAFE_ID.fullmatch(ident):
        return None
    info = readout.get("experiment") if isinstance(readout.get("experiment"), dict) else {}
    name = sanitize(definition.get("name") or "", patterns, redactions)
    hypothesis = sanitize(definition.get("hypothesis") or "", patterns, redactions)
    arms = []
    for arm in readout.get("arms") or []:
        if not isinstance(arm, dict):
            continue
        arm_name = arm.get("name")
        if not isinstance(arm_name, str) or not SAFE_TOKEN.fullmatch(arm_name):
            continue
        mix = []
        for crew_row in arm.get("crew_mix") or []:
            if not isinstance(crew_row, dict):
                continue
            crew, tasks = crew_row.get("crew"), crew_row.get("tasks")
            if is_gap_crew(crew) or is_gap_model(crew_row.get("model")):
                dropped["experiments"] += 1
                continue
            if isinstance(crew, str) and SAFE_TOKEN.fullmatch(crew) and is_number(tasks):
                mix.append({"crew": crew, "tasks": tasks})
        segments = []
        for segment in arm.get("segments") or []:
            if isinstance(segment, dict) and is_number(segment.get("segment")) and is_number(segment.get("n")):
                segments.append({"n": segment["n"], "segment": segment["segment"]})
        projected = {
            "control": bool(arm.get("control")),
            "crew_mix": mix,
            "drifted": bool(arm.get("drifted")),
            "n": whole(arm.get("n")) or 0,
            "name": arm_name,
            "segments": segments,
            "tasks_explorer_unobserved": whole(arm.get("tasks_explorer_unobserved")) or 0,
            "tasks_with_explorer_call": whole(arm.get("tasks_with_explorer_call")) or 0,
            "weight": arm.get("weight") if is_number(arm.get("weight")) else None,
        }
        if arm.get("retired_segment") is None or is_number(arm.get("retired_segment")):
            projected["retired_segment"] = arm.get("retired_segment")
        usage = project_usage(arm.get("effort_breakdown"), dropped, "experiments")
        if usage is not None:
            projected["usage"] = usage
        arms.append(projected)
    warnings = collections.Counter()
    for warning in readout.get("warnings") or []:
        if isinstance(warning, dict) and isinstance(warning.get("kind"), str) and SAFE_KEY.fullmatch(warning["kind"]):
            warnings[warning["kind"]] += 1
    verdict = readout.get("verdict") if isinstance(readout.get("verdict"), dict) else {}
    reasons = [
        sanitize(reason, patterns, redactions)
        for reason in verdict.get("reasons") or []
        if isinstance(reason, str)
    ]
    enrollment = numeric_map(readout.get("enrollment")) or {}
    lagging = readout.get("lagging") if isinstance(readout.get("lagging"), dict) else {}
    ratio = readout.get("sample_ratio") if isinstance(readout.get("sample_ratio"), dict) else {}
    per_protocol = readout.get("per_protocol") if isinstance(readout.get("per_protocol"), dict) else None
    guardrails = []
    for guard in readout.get("guardrails") or []:
        if not isinstance(guard, dict):
            continue
        metric = guard.get("metric")
        if not isinstance(metric, str) or not SAFE_TOKEN.fullmatch(metric):
            continue
        arms_out = []
        for arm in guard.get("arms") or []:
            if not isinstance(arm, dict) or not isinstance(arm.get("arm"), str) or not SAFE_TOKEN.fullmatch(arm["arm"]):
                continue
            item = {
                "arm": arm["arm"],
                "estimate": arm.get("estimate") if arm.get("estimate") is None or is_number(arm.get("estimate")) else None,
                "status": arm.get("status") if isinstance(arm.get("status"), str) and SAFE_KEY.fullmatch(arm["status"]) else None,
            }
            interval = number_list(arm.get("interval"), 2)
            if interval is not None:
                item["interval"] = interval
            if is_number(arm.get("limit")) or isinstance(arm.get("limit"), str) and SAFE_LABEL.fullmatch(arm["limit"]):
                item["limit"] = arm["limit"]
            arms_out.append(item)
        threshold = guard.get("threshold")
        guardrails.append({
            "arms": arms_out,
            "metric": metric,
            "threshold": threshold if isinstance(threshold, str) and SAFE_LABEL.fullmatch(threshold) else None,
        })
    concluded = definition.get("concluded_arm")
    return {
        "arms": arms,
        "as_of": readout.get("as_of") if isinstance(readout.get("as_of"), str) else None,
        "concluded_arm": concluded if concluded is None or (isinstance(concluded, str) and SAFE_TOKEN.fullmatch(concluded)) else None,
        "enrollment": enrollment,
        "guardrail_definition": {
            key: value for key, value in (definition.get("guardrails") or {}).items()
            if isinstance(key, str) and SAFE_KEY.fullmatch(key) and isinstance(value, str) and SAFE_LABEL.fullmatch(value)
        } if isinstance(definition.get("guardrails"), dict) else {},
        "guardrails": guardrails,
        "horizon_at": info.get("horizon_at") if isinstance(info.get("horizon_at"), str) else None,
        "hypothesis": hypothesis,
        "id": ident,
        "lagging": {
            "open_regression_windows": whole(lagging.get("open_regression_windows")) or 0,
            "open_tasks": whole(lagging.get("open_tasks")) or 0,
            "regression_window_days": whole(lagging.get("regression_window_days")) or 0,
        },
        "max_days": whole(definition.get("max_days")),
        "metrics": [item for item in (project_metric(metric) for metric in readout.get("metrics") or []) if item],
        "min_delivered_rate": info.get("min_delivered_rate") if is_number(info.get("min_delivered_rate")) else None,
        "min_sample": whole(definition.get("min_sample")),
        "mode": definition.get("mode") if isinstance(definition.get("mode"), str) and SAFE_KEY.fullmatch(definition["mode"]) else None,
        "name": name,
        "per_protocol": None if per_protocol is None else {
            "label": sanitize(per_protocol.get("label") or "", patterns, redactions)
            if isinstance(per_protocol.get("label"), str) else None,
            "metric": project_metric(per_protocol.get("metric")),
        },
        "population": {
            "complexity": [
                item for item in (definition.get("population") or {}).get("complexity") or []
                if isinstance(item, str) and SAFE_KEY.fullmatch(item)
            ],
        } if isinstance(definition.get("population"), dict) else {},
        "primary_metric": definition.get("primary_metric")
        if isinstance(definition.get("primary_metric"), str) and SAFE_TOKEN.fullmatch(definition["primary_metric"]) else None,
        "sample_ratio": {
            "alpha": ratio.get("alpha") if is_number(ratio.get("alpha")) else None,
            "chi_square": ratio.get("chi_square") if is_number(ratio.get("chi_square")) else None,
            "df": whole(ratio.get("df")),
            "mismatch": bool(ratio.get("mismatch")),
            "p_value": ratio.get("p_value") if is_number(ratio.get("p_value")) else None,
        },
        "schema_version": SCHEMA_VERSION,
        "segment": whole(definition.get("segment")),
        "started_at": info.get("started_at") if isinstance(info.get("started_at"), str) else None,
        "status": "concluded",
        "updated_at": definition.get("updated_at") if isinstance(definition.get("updated_at"), str) else None,
        "verdict": {
            "arm": verdict.get("arm") if verdict.get("arm") is None
            or (isinstance(verdict.get("arm"), str) and SAFE_TOKEN.fullmatch(verdict["arm"])) else None,
            "horizon_reached": bool(verdict.get("horizon_reached")),
            "label": sanitize(verdict.get("label") or "", patterns, redactions)
            if isinstance(verdict.get("label"), str) else None,
            "reasons": reasons,
            "state": verdict.get("state") if isinstance(verdict.get("state"), str) and SAFE_KEY.fullmatch(verdict["state"]) else None,
        },
        "warning_kinds": dict(sorted(warnings.items())),
    }


def project_experiments(pairs, dropped, patterns, redactions):
    projected = []
    for definition, readout in pairs:
        item = project_experiment(definition, readout, dropped, patterns, redactions)
        if item is not None:
            projected.append(item)
    projected.sort(key=lambda item: (item.get("name") or "", item["id"]))
    return projected
