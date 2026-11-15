"""Settled model-rank projections."""

import re

from .common import (
    RANK_EXECUTION,
    RANK_MEASURE_FIELDS,
    RANK_RULES,
    RANK_SOURCE,
    RANK_TIERS,
    SAFE_KEY,
    SAFE_LABEL,
    SAFE_TOKEN,
    SCHEMA_VERSION,
    WINDOW,
    is_gap_model,
    is_number,
    is_rank_dropped_crew,
    numeric_map,
    whole,
    window_of,
)
from .redaction import (
    sanitize,
)


def rank_text(value, patterns, redactions):
    """Free text from the rank board, sanitized; anything not a string is dropped."""
    if not isinstance(value, str) or not value.strip():
        return None
    return sanitize(" ".join(value.split()), patterns, redactions)


def project_rank_measure(measure, patterns, redactions):
    if not isinstance(measure, dict):
        return None
    key, label = measure.get("key"), measure.get("label")
    if not isinstance(key, str) or not SAFE_KEY.fullmatch(key):
        return None
    if not isinstance(label, str) or not SAFE_LABEL.fullmatch(label):
        return None
    item = {"key": key, "label": label}
    for field in ("weight", "sign"):
        item[field] = measure.get(field) if is_number(measure.get(field)) else None
    for field in ("pillar", "status"):
        value = measure.get(field)
        item[field] = value if isinstance(value, str) and SAFE_KEY.fullmatch(value) else None
    units = measure.get("units")
    item["units"] = units if isinstance(units, str) and SAFE_LABEL.fullmatch(units) else None
    item["definition"] = rank_text(measure.get("definition"), patterns, redactions)
    item["reason"] = rank_text(measure.get("reason"), patterns, redactions)
    return item


def project_rank_row_measures(measures, keys, patterns, redactions):
    out = {}
    if not isinstance(measures, dict):
        return out
    for key in keys:
        entry = measures.get(key)
        if not isinstance(entry, dict):
            continue
        item = {field: entry.get(field) if is_number(entry.get(field)) else None for field in RANK_MEASURE_FIELDS}
        status = entry.get("status")
        item["status"] = status if isinstance(status, str) and SAFE_KEY.fullmatch(status) else None
        unit = entry.get("unit")
        item["unit"] = unit if isinstance(unit, str) and SAFE_LABEL.fullmatch(unit) else None
        item["reason"] = rank_text(entry.get("reason"), patterns, redactions)
        out[key] = item
    return out


def project_rank_row(row, measure_keys, dropped, patterns, redactions):
    if not isinstance(row, dict):
        return None
    model = row.get("model")
    if is_gap_model(model):
        dropped["rank"] += 1
        return None
    if not isinstance(model, str) or not SAFE_TOKEN.fullmatch(model):
        return None
    units = row.get("units")
    if not is_number(units):
        return None
    rank = row.get("rank")
    eligible = row.get("eligible") is True
    if not eligible or isinstance(rank, bool) or not isinstance(rank, int):
        rank = None
    label = row.get("rank_label")
    band = row.get("band_size")
    projected = {
        "model": model,
        "eligible": eligible,
        "rank": rank,
        "rank_label": label if rank is not None and isinstance(label, str) and re.fullmatch(r"[0-9]{1,3}=?", label) else None,
        "band_size": band if rank is not None and isinstance(band, int) and not isinstance(band, bool) else None,
        "ineligible_reason": None if eligible else rank_text(row.get("ineligible_reason"), patterns, redactions),
        "units": units,
        "tasks_by_tier": {
            tier: count for tier, count in (numeric_map(row.get("tasks_by_tier")) or {}).items()
            if tier in RANK_TIERS and is_number(count)
        },
        "score": row.get("score") if is_number(row.get("score")) else None,
        "raw_score": row.get("raw_score") if is_number(row.get("raw_score")) else None,
        "weights_measured": row.get("weights_measured") if is_number(row.get("weights_measured")) else None,
        "landed_tasks": row.get("landed_tasks") if is_number(row.get("landed_tasks")) else None,
        "landed_rate": row.get("landed_rate") if is_number(row.get("landed_rate")) else None,
    }
    interval = row.get("interval")
    if isinstance(interval, dict) and is_number(interval.get("p10")) and is_number(interval.get("p90")):
        projected["interval"] = {"p10": interval["p10"], "p90": interval["p90"]}
    else:
        projected["interval"] = None
    cost = row.get("cost")
    if isinstance(cost, dict):
        projected["cost"] = {
            "ratio": cost.get("ratio") if is_number(cost.get("ratio")) else None,
            "per_task": cost.get("per_task") if is_number(cost.get("per_task")) else None,
            "expected_per_task": cost.get("expected_per_task") if is_number(cost.get("expected_per_task")) else None,
            "coverage": cost.get("coverage") if is_number(cost.get("coverage")) else None,
            "cost_unknown": cost.get("cost_unknown") is True,
        }
    else:
        projected["cost"] = None
    projected["measures"] = project_rank_row_measures(row.get("measures"), measure_keys, patterns, redactions)
    crews = []
    for entry in row.get("crews") or []:
        if not isinstance(entry, dict):
            continue
        crew, tasks = entry.get("crew"), entry.get("tasks")
        if is_rank_dropped_crew(crew):
            dropped["rank"] += 1
            continue
        if isinstance(crew, str) and SAFE_TOKEN.fullmatch(crew) and is_number(tasks):
            crews.append({"crew": crew, "tasks": tasks})
    projected["crews"] = crews
    tiers = []
    for entry in row.get("tiers") or []:
        if not isinstance(entry, dict) or entry.get("tier") not in RANK_TIERS:
            continue
        tiers.append({
            "tier": entry["tier"],
            "tasks": entry.get("tasks") if is_number(entry.get("tasks")) else None,
            "score": entry.get("score") if is_number(entry.get("score")) else None,
            "cost_per_task": entry.get("cost_per_task") if is_number(entry.get("cost_per_task")) else None,
            "cost_coverage": entry.get("cost_coverage") if is_number(entry.get("cost_coverage")) else None,
            "cost_unknown": entry.get("cost_unknown") is True,
        })
    projected["tiers"] = tiers
    single = single_tier(row.get("single_tier"))
    if single is not None:
        projected["single_tier"] = single
    return projected


def single_tier(value):
    """Orbit's single-tier flag on an eligible row: the tier's name, True, or None.

    Orbit may name the tier (``"hard"``), set ``true``, or carry an object
    with a ``tier``; anything else is not a flag.
    """
    if isinstance(value, dict):
        value = value.get("tier", True if value else None)
    if value is True:
        return True
    if isinstance(value, str) and value in RANK_TIERS:
        return value
    return None


def eligibility_rule(payload, rules, patterns, redactions):
    """Orbit's eligibility rule as one sentence.

    Orbit's own text wins when the board carries one (``eligibility_rule``, or
    ``rules.eligibility``); otherwise the sentence is stated from the board's
    numeric rules, so a change of Orbit's rule changes it with no edit here.
    """
    rules_in = payload.get("rules") if isinstance(payload.get("rules"), dict) else {}
    for text in (payload.get("eligibility_rule"), rules_in.get("eligibility")):
        stated = rank_text(text, patterns, redactions)
        if stated is not None:
            return stated
    tasks, tiers, per_tier = rules.get("min_tasks"), rules.get("min_tiers"), rules.get("min_tier_tasks")
    if not is_number(tasks):
        return None
    sentence = f"At least {tasks:g} implemented tasks"
    if is_number(tiers) and is_number(per_tier):
        if tiers == 1:
            sentence += f", with at least {per_tier:g} in one assessed tier"
        else:
            sentence += f" spanning at least {tiers:g} assessed tiers with at least {per_tier:g} tasks each"
    sentence += "."
    if is_number(rules.get("min_eligible_models")):
        sentence += f" The board needs {rules['min_eligible_models']:g} such models."
    return sentence


def project_rank(payload, dropped, patterns, redactions):
    """The settled 30d managed implementer-model rank board, public fields only.

    The ranked window ends at the settled cutoff, ``settle_lag`` before the
    snapshot, so ``live`` and ``provisional`` are both false. A live board is
    refused: it is provisional and is never published. Copied: the settled
    window, settle lag and execution scope, the qualification rules,
    ``scales_source`` and ``qualified``, Orbit's eligibility rule as one
    sentence, each non-eligible model's reason, each measure's label, weight,
    status and sanitized definition, the not-scored count by reason, and per
    model its band, score, p10-p90 interval, cost per task and ratio, tier
    mix, landed rate, per-measure contributions, crews (with their task
    counts; a bare crew's effort is unknown) and per-tier scores. The crew
    ``system`` is dropped and counted with the other gap crews. Not copied:
    paired probabilities, z-scores, per-effort usage splits, the unattributed
    crew list and per-row execution splits.
    """
    if not isinstance(payload, dict):
        raise SystemExit("rank board did not return an object")
    if payload.get("live") is not False or payload.get("provisional") is not False:
        raise SystemExit("rank board must be the settled board (live and provisional false)")
    if payload.get("execution") != RANK_EXECUTION:
        raise SystemExit("rank board must count managed tasks")
    if payload.get("window") != WINDOW:
        raise SystemExit(f"rank board must be a {WINDOW} window")
    measures = []
    for measure in payload.get("measures") or []:
        projected = project_rank_measure(measure, patterns, redactions)
        if projected is not None:
            measures.append(projected)
    keys = [measure["key"] for measure in measures]
    rows = []
    for row in payload.get("rows") or []:
        projected = project_rank_row(row, keys, dropped, patterns, redactions)
        if projected is not None:
            rows.append(projected)
    rules_in = payload.get("rules") if isinstance(payload.get("rules"), dict) else {}
    rules = {key: rules_in.get(key) if is_number(rules_in.get(key)) else None for key in RANK_RULES}
    percentiles = rules_in.get("interval_percentiles")
    rules["interval_percentiles"] = (
        list(percentiles) if isinstance(percentiles, list) and len(percentiles) == 2 and all(is_number(v) for v in percentiles) else None
    )
    not_scored = payload.get("not_scored") if isinstance(payload.get("not_scored"), dict) else {}
    unattributed = payload.get("unattributed") if isinstance(payload.get("unattributed"), dict) else {}
    settle_lag = payload.get("settle_lag")
    status = payload.get("status")
    scales = payload.get("scales_source")
    return {
        "computed_at": payload.get("computed_at") if isinstance(payload.get("computed_at"), str) else None,
        "eligible_models": whole(payload.get("eligible_models")),
        "eligibility_rule": eligibility_rule(payload, rules, patterns, redactions),
        "execution": RANK_EXECUTION,
        "live": False,
        "measures": measures,
        "not_scored": {
            "count": whole(not_scored.get("count")),
            "reasons": numeric_map(not_scored.get("reasons")) or {},
        },
        "provisional": False,
        "qualified": payload.get("qualified") is True,
        "role": "implementers",
        "rows": rows,
        "rules": rules,
        "scales_source": scales if isinstance(scales, str) and SAFE_KEY.fullmatch(scales) else None,
        "schema_version": SCHEMA_VERSION,
        "settle_lag": settle_lag if isinstance(settle_lag, str) and re.fullmatch(r"[0-9]{1,4}[smhdw]", settle_lag) else None,
        "source": RANK_SOURCE,
        "status": status if isinstance(status, str) and SAFE_KEY.fullmatch(status) else None,
        "tasks_scanned": whole(payload.get("tasks_scanned")),
        "unattributed_tasks": whole(unattributed.get("tasks")),
        "weights_total": payload.get("weights_total") if is_number(payload.get("weights_total")) else None,
        "window": window_of(payload),
    }
