"""Public scorecard and by-tier projections."""

import collections

from .common import (
    MIN_SUPPORT_DEFAULT,
    ROLES,
    SAFE_KEY,
    SAFE_LABEL,
    SAFE_TOKEN,
    SCHEMA_VERSION,
    TIER_ORDER,
    is_gap_crew,
    is_gap_model,
    is_number,
    numeric_map,
    project_usage,
    window_of,
)


def project_terms(terms):
    out = []
    if not isinstance(terms, list):
        return out
    for term in terms:
        if not isinstance(term, dict):
            continue
        key, label, weight = term.get("key"), term.get("label"), term.get("weight")
        if not isinstance(key, str) or not SAFE_KEY.fullmatch(key):
            continue
        if not isinstance(label, str) or not SAFE_LABEL.fullmatch(label):
            continue
        if not is_number(weight):
            continue
        item = {"key": key, "label": label, "weight": weight}
        group = term.get("group")
        if isinstance(group, str) and SAFE_KEY.fullmatch(group):
            item["group"] = group
        out.append(item)
    return out


def score_key(terms, unit, fleet_average):
    credit = [term["label"].lower() for term in terms if term["weight"] > 0]
    debit = [term["label"].lower() for term in terms if term["weight"] < 0]
    credit_text = ", ".join(credit) if credit else "none"
    debit_text = ", ".join(debit) if debit else "none"
    return (
        f"Score: per 100 {unit}, credit for {credit_text}; "
        f"debits for {debit_text}. The fleet average is {fleet_average:.1f}."
    )


def project_stats(stats):
    if not isinstance(stats, list):
        return None
    out = []
    for item in stats:
        if not isinstance(item, dict):
            continue
        key, label, value = item.get("key"), item.get("label"), item.get("value")
        if not isinstance(key, str) or not SAFE_KEY.fullmatch(key):
            continue
        if not isinstance(label, str) or not SAFE_LABEL.fullmatch(label):
            continue
        if value is not None and not is_number(value) and not isinstance(value, bool):
            continue
        out.append({"key": key, "label": label, "value": value})
    return out


def project_string_list(values):
    if not isinstance(values, list):
        return None
    out = []
    for value in values:
        if not isinstance(value, str) or not SAFE_KEY.fullmatch(value):
            return None
        out.append(value)
    return out


def project_effort(obj):
    """The row's effort identity: ``reasoning_effort`` and ``effort_label``.

    Each is copied only when it passes its allowlist; a row with no recorded
    effort field (a snapshot from before scorecards split rows by effort)
    gets neither key, and ``unknown`` is kept as the value ``unknown``. No
    effort is ever read from crew configuration: an unknown effort stays unknown.
    """
    out = {}
    effort = obj.get("reasoning_effort")
    if isinstance(effort, str) and SAFE_TOKEN.fullmatch(effort):
        out["reasoning_effort"] = effort
    label = obj.get("effort_label")
    if isinstance(label, str) and SAFE_LABEL.fullmatch(label):
        out["effort_label"] = label
    return out


def project_row(row, min_support, unit, dropped, board):
    if not isinstance(row, dict):
        return None
    crew, model = row.get("crew"), row.get("model")
    if is_gap_crew(crew) or is_gap_model(model):
        dropped[board] += 1
        return None
    if not isinstance(crew, str) or not SAFE_TOKEN.fullmatch(crew):
        return None
    if not isinstance(model, str) or not SAFE_TOKEN.fullmatch(model):
        return None
    units = row.get("units")
    if not is_number(units):
        return None
    below = bool(row.get("below_support")) or bool(row.get("unjudged")) or units < min_support
    rank = row.get("rank")
    if below or isinstance(rank, bool) or not isinstance(rank, int):
        rank = None
    projected = {
        "below_support": below,
        "crew": crew,
        "model": model,
        "rank": rank,
        "unit": unit,
        "units": units,
        "unjudged": bool(row.get("unjudged")),
    }
    projected.update(project_effort(row))
    for key in ("raw", "score", "score_base"):
        if is_number(row.get(key)):
            projected[key] = row[key]
    for key in ("counts", "expected", "per_100", "term_units"):
        copied = numeric_map(row.get(key))
        if copied is not None and key in row:
            projected[key] = copied
    reviewed = row.get("reviewed_units")
    if is_number(reviewed):
        projected["reviewed_units"] = reviewed
    runs_without = row.get("runs_without_model")
    if is_number(runs_without):
        projected["runs_without_model"] = runs_without
    provisional = row.get("provisional")
    if is_number(provisional):
        projected["provisional"] = provisional
    terms = project_string_list(row.get("provisional_terms"))
    if terms is not None and "provisional_terms" in row:
        projected["provisional_terms"] = terms
    stats = project_stats(row.get("stats"))
    if stats is not None and "stats" in row:
        projected["stats"] = stats
    usage = project_usage(row.get("effort_breakdown"), dropped, board)
    if usage is not None:
        projected["usage"] = usage
    return projected


def project_board(card, provisional, dropped, board, settled=False):
    min_support = card.get("min_support")
    if isinstance(min_support, bool) or not isinstance(min_support, int):
        min_support = MIN_SUPPORT_DEFAULT
    unit = card.get("unit") if isinstance(card.get("unit"), str) and SAFE_LABEL.fullmatch(card["unit"]) else "units"
    fleet = card.get("fleet_average") if is_number(card.get("fleet_average")) else None
    terms = project_terms(card.get("terms"))
    rows = []
    for row in card.get("rows") or []:
        projected = project_row(row, min_support, unit, dropped, board)
        if projected is not None:
            rows.append(projected)
    role = card.get("role") if card.get("role") in ROLES else board.split("_", 1)[0]
    projected = {
        "fleet_average": fleet,
        "min_support": min_support,
        "provisional": provisional,
        "role": role,
        "rows": rows,
        "score_key": score_key(terms, unit, fleet) if fleet is not None else None,
        "settled": settled,
        "terms": terms,
        "unit": unit,
        "window": window_of(card),
    }
    scanned = card.get("tasks_scanned")
    if isinstance(scanned, int) and not isinstance(scanned, bool):
        projected["tasks_scanned"] = scanned
    provisional_units = card.get("provisional")
    if isinstance(provisional_units, int) and not isinstance(provisional_units, bool):
        projected["provisional_units"] = provisional_units
    return projected


def effort_sort_key(item):
    return (item.get("reasoning_effort") or "", item.get("effort_label") or "")


def project_cells(card, dropped):
    min_support = card.get("min_support")
    if isinstance(min_support, bool) or not isinstance(min_support, int):
        min_support = MIN_SUPPORT_DEFAULT
    cells = []
    for cell in card.get("cells") or []:
        if not isinstance(cell, dict):
            continue
        crew, model, count = cell.get("crew"), cell.get("model"), cell.get("n")
        if not is_number(count) or count <= 0:
            continue
        if is_gap_crew(crew) or is_gap_model(model):
            dropped["implementers_by_tier"] += 1
            continue
        tier, kind = cell.get("tier"), cell.get("type")
        if tier not in TIER_ORDER or not isinstance(kind, str) or not SAFE_KEY.fullmatch(kind):
            continue
        if not isinstance(crew, str) or not SAFE_TOKEN.fullmatch(crew):
            continue
        if not isinstance(model, str) or not SAFE_TOKEN.fullmatch(model):
            continue
        item = {
            "below_support": count < min_support,
            "crew": crew,
            "model": model,
            "n": count,
            "rank": None,
            "tier": tier,
            "type": kind,
            "unit": "tasks",
            "units": count,
        }
        item.update(project_effort(cell))
        for key in ("crew_mean", "raw", "score"):
            if is_number(cell.get(key)):
                item[key] = cell[key]
        cells.append(item)
    grouped = collections.defaultdict(list)
    for cell in cells:
        if not cell["below_support"]:
            grouped[(cell["tier"], cell["type"])].append(cell)
    for group in grouped.values():
        group.sort(key=lambda cell: (
            -cell.get("crew_mean", cell.get("score", 0)), cell["crew"], cell["model"], effort_sort_key(cell),
        ))
        for index, cell in enumerate(group, 1):
            cell["rank"] = index
    cells.sort(key=lambda cell: (
        TIER_ORDER.index(cell["tier"]),
        cell["type"],
        cell["rank"] is None,
        cell["rank"] or 0,
        cell["crew"],
        cell["model"],
        effort_sort_key(cell),
    ))
    return {
        "cells": cells,
        "min_support": min_support,
        "provisional": False,
        "role": "implementers",
        "settled": False,
        "unit": "tasks",
        "window": window_of(card),
    }


def assemble_scorecards(cards, until_supported, dropped):
    reviewers = {
        "provisional": project_board(cards["reviewers"], True, dropped, "reviewers_provisional", settled=False),
        "settled": project_board(cards["reviewers_settled"], False, dropped, "reviewers_settled", settled=True)
        if until_supported else None,
    }
    return {
        "implementers": project_board(cards["implementers"], False, dropped, "implementers"),
        "implementers_by_tier": project_cells(cards["implementers_by_type"], dropped),
        "min_support_default": MIN_SUPPORT_DEFAULT,
        "pilots": project_board(cards["pilots"], False, dropped, "pilots"),
        "reviewers": reviewers,
        "roles": list(ROLES),
        "roles_omitted": ["orchestrators"],
        "schema_version": SCHEMA_VERSION,
    }
