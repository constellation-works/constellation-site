"""Ranking boards (split from build.py)."""

import html
import json
import math
import pathlib
import statistics
import sys
import analytics_page
from build_common import GAP_CREWS, GAP_MODELS, RANK_NON_CREW, as_number, fmt_count, fmt_num, join_words
from build_ranking_data import TIER_LABELS, bar_scale, crew_label, fmt_score, rank_text, role_rows, score_bar


OVERALL_RULE = {
    "weights": (("implementers", 60), ("reviewers", 25), ("pilots", 15)),
    "min_roles": 2,
}

ROLE_ORDER = ("implementers", "reviewers", "pilots")

ROLE_NOUN = {"implementers": "implementer", "reviewers": "reviewer", "pilots": "pilot"}

ROLE_TITLE = {"implementers": "Implementers", "reviewers": "Reviewers", "pilots": "Pilots"}

RANK_TIERS = ("low", "medium", "hard", "xhard")

MODEL_PROVIDERS = (("gpt", "gpt"), ("claude", "claude"), ("gemini", "gemini"), ("grok", "grok"), ("muse", "muse"))

SNAPSHOT_TREE = "https://github.com/constellation-works/constellation-site/tree/main/data/analytics/"

def provider(model):
    for prefix, name in MODEL_PROVIDERS:
        if isinstance(model, str) and model.startswith(prefix):
            return name
    return "other"

def model_dot(model):
    return f'<span class="prov-dot prov-{provider(model)}" aria-hidden="true"></span>'

def load_rank(directory):
    """rank.json of a snapshot, or None when the snapshot predates the rank board."""
    path = pathlib.Path(directory) / "rank.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"{path}: invalid JSON ({exc})")
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        sys.exit(f"{path}: expected an object with rows")
    # A new snapshot is the settled board. One published while the live board
    # was current, and one from before that, still load. Either way live and
    # provisional agree.
    live = data.get("live")
    if not isinstance(live, bool) or data.get("provisional") is not live or data.get("execution") != "managed":
        sys.exit(f"{path}: the public rank board must be the managed board, live and provisional or settled")
    window = data.get("window")
    if not isinstance(window, dict) or window.get("key") != "30d":
        sys.exit(f"{path}: the rank board must be a 30d window")
    if not isinstance(window.get("since"), str) or not isinstance(window.get("until"), str):
        sys.exit(f"{path}: the rank board is missing its UTC window")
    return data

def rank_rows(rank):
    """(ranked, not ranked) model rows, gaps removed.

    Ranked rows go in rank order and, inside a shared band, by score, highest first, then model name
    (STD-07 §R36), so a band reads in the order of the figure the board shows. The MVP's writer still
    follows Orbit's own band order (cheapest first); that is scripts/crew_rankings.py's rule, not this view's.
    """
    rows = [
        row for row in rank.get("rows") or []
        if isinstance(row, dict) and isinstance(row.get("model"), str)
        and row["model"] not in GAP_MODELS and as_number(row.get("units"))
    ]
    ranked = [row for row in rows if isinstance(row.get("rank"), int) and not isinstance(row.get("rank"), bool)
              and row.get("eligible") is True and as_number(row.get("score"))]
    ranked.sort(key=lambda row: (row["rank"], -row["score"], row["model"]))
    rest = [row for row in rows if row not in ranked]
    return ranked, rest

def pooled_models(shown):
    """Ranked crews pooled into their model: units-weighted mean score.

    Every effort row of a model is pooled; its crews are listed by label
    (``sol · high``) so the pooling inputs stay distinguishable.
    """
    pooled = {}
    for row in shown["rows"]:
        if row["rank"] is None or row["score"] is None or not row["units"]:
            continue
        slot = pooled.setdefault(row["model"], {"weighted": 0.0, "units": 0, "crews": [], "labelled": False})
        slot["labelled"] = slot["labelled"] or row.get("effort") is not None
        slot["weighted"] += row["score"] * row["units"]
        slot["units"] += row["units"]
        label = crew_label(row)
        if label not in slot["crews"]:
            slot["crews"].append(label)
    out = {}
    for model, slot in pooled.items():
        out[model] = {"score": slot["weighted"] / slot["units"], "units": slot["units"], "crews": slot["crews"],
                      "labelled": slot["labelled"]}
    return out

def place_models(models):
    """1-based place by score, highest first."""
    order = sorted(models, key=lambda model: (-models[model]["score"], model))
    return {model: index for index, model in enumerate(order, 1)}

def role_boards(scorecards):
    if not isinstance(scorecards, dict):
        sys.exit("scorecards.json: expected an object")
    implementers = scorecards.get("implementers")
    pilots = scorecards.get("pilots")
    reviewers = scorecards.get("reviewers")
    if not isinstance(implementers, dict) or not isinstance(pilots, dict) or not isinstance(reviewers, dict):
        sys.exit("scorecards.json: implementers, reviewers and pilots are required")
    provisional = reviewers.get("provisional")
    if not isinstance(provisional, dict):
        sys.exit("scorecards.json: reviewers.provisional is required")
    return {
        "implementers": role_rows(implementers, "implementers"),
        "reviewers": role_rows(provisional, "reviewers provisional"),
        "pilots": role_rows(pilots, "pilots"),
    }

def overall_models(scorecards, rule=None):
    """The All-roles index: models ranked across implementing, reviewing and piloting.

    Each role's crews are pooled into their model, units-weighted, and indexed
    by that board's fleet average. A model enters the index only with a ranked
    crew in at least ``rule["min_roles"]`` roles; its index is the weighted
    mean over the roles it holds, the weights rescaled to sum to 1. Nothing is
    imputed for a missing role. Models ranked in fewer roles are returned in
    ``one_role`` as (model, role), not ranked.
    """
    rule = rule or OVERALL_RULE
    boards = role_boards(scorecards)
    roles = {}
    for role in ROLE_ORDER:
        shown = boards[role]
        fleet = shown["fleet"]
        pooled = pooled_models(shown)
        places = place_models(pooled)
        for model, slot in pooled.items():
            slot["place"] = places[model]
            slot["index"] = slot["score"] / fleet * 100 if fleet else None
        roles[role] = {"models": pooled, "of": len(pooled), "fleet": fleet}
    weights = rule["weights"]
    min_roles = rule["min_roles"]
    models = []
    for role in ROLE_ORDER:
        models.extend(model for model in roles[role]["models"] if model not in models)
    rows = []
    one_role = []
    for model in models:
        cells = {}
        weighted = held = 0.0
        units = 0
        crews = []
        labelled = False
        for role, weight in weights:
            slot = roles[role]["models"].get(model)
            if slot is None or slot.get("index") is None:
                cells[role] = None
                continue
            cells[role] = {"index": slot["index"], "score": slot["score"], "place": slot["place"],
                           "of": roles[role]["of"], "units": slot["units"]}
            weighted += weight * slot["index"]
            held += weight
            units += slot["units"]
            crews.extend(crew for crew in slot["crews"] if crew not in crews)
            labelled = labelled or bool(slot.get("labelled"))
        present = [role for role, _weight in weights if cells[role] is not None]
        if len(present) < min_roles or not held:
            if present:
                one_role.append((model, present[0]))
            continue
        rows.append({"model": model, "overall": weighted / held, "cells": cells, "units": units, "crews": crews,
                     "labelled": labelled, "roles": present})
    rows.sort(key=lambda row: (-row["overall"], row["model"]))
    for index, row in enumerate(rows, 1):
        row["place"] = index
    one_role.sort()
    return {"rows": rows, "one_role": one_role, "roles": roles}

def overall_rule_text(rule=None):
    rule = rule or OVERALL_RULE
    total = sum(weight for _role, weight in rule["weights"]) or 1
    parts = " + ".join(f"{round(weight / total * 100)}% {ROLE_NOUN[role]}" for role, weight in rule["weights"])
    words = {1: "one", 2: "two", 3: "three"}
    need = words.get(rule["min_roles"], str(rule["min_roles"]))
    return (
        "Each role's score divided by its fleet average, so 100 is average everywhere, "
        f"with crews pooled into their model by units of work. Index = {parts}, over the roles a model holds: "
        f"it needs a ranked crew in at least {need} roles, and the weights of the roles it holds are rescaled "
        "to sum to 1. A missing role is never filled in."
    )

def stat_cards(items, label):
    e = html.escape
    cells = "".join(
        f'<li class="stat"><span class="stat-label">{e(name)}</span>'
        f'<span class="stat-line"><span class="stat-value">{e(value)}</span>'
        f'<span class="stat-sub">{e(sub)}</span></span></li>'
        for name, value, sub in items
    )
    return f'<ul class="stat-cards" aria-label="{e(label)}">{cells}</ul>'

def ordinal(number):
    suffix = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"

def rank_crew_entries(row):
    """Labels for one model's rank crews, in Orbit's order.

    ``system`` and attribution gaps are omitted. A key that carries an effort
    (``sol@high``) is that recorded label. Model rank pools every effort of a
    model, so a bare key (``sol``) means its efforts are not broken out, not
    that they went unrecorded: it is the crew name alone, never
    ``effort unknown`` (ORB-24204). A snapshot's ``effort_estimate`` (written
    before ORB-23846) is ignored.
    """
    out = []
    index = {}
    for entry in row.get("crews") or []:
        if not isinstance(entry, dict):
            continue
        crew = entry.get("crew")
        if not isinstance(crew, str) or not crew or crew == RANK_NON_CREW or crew in GAP_CREWS:
            continue
        tasks = entry.get("tasks") if as_number(entry.get("tasks")) else None
        label = crew
        if label in index:
            slot = out[index[label]]
            if tasks is not None:
                slot["tasks"] = tasks if slot["tasks"] is None else slot["tasks"] + tasks
            continue
        index[label] = len(out)
        out.append({"label": label, "tasks": tasks})
    return out

def rank_crew_line(row):
    """One model's rank crews on one line, each crew named once (``sol: high, xhigh``)."""
    return analytics_page.crew_groups_text(item["label"] for item in rank_crew_entries(row))

def podium_from_rank(rank):
    """The podium's top three from Model rank, in rank order (by score inside a band), with their Rank score."""
    ranked, _rest = rank_rows(rank)
    items = []
    for row in ranked[:3]:
        label = row.get("rank_label") or str(row["rank"])
        interval = row.get("interval") or {}
        note = (f'p10–p90 {fmt_score(interval["p10"])}–{fmt_score(interval["p90"])}'
                if as_number(interval.get("p10")) and as_number(interval.get("p90")) else "Model rank score")
        items.append({"place": ordinal(row["rank"]) + ("=" if label.endswith("=") else ""), "model": row["model"],
                      "crews": rank_crew_line(row), "score": row["score"], "note": note})
    return items

def podium_from_index(overall):
    """The podium's top three from the All-roles index (a snapshot without Model rank)."""
    items = []
    for row in overall["rows"][:3]:
        present = [(role, cell["index"]) for role, cell in row["cells"].items() if cell is not None]
        strongest = max(present, key=lambda item: item[1])[0] if present else None
        items.append({"place": ordinal(row["place"]), "model": row["model"], "crews": crews_text(row),
                      "score": row["overall"], "note": f"strongest as {ROLE_NOUN[strongest]}" if strongest else ""})
    return items

def podium_html(items, label):
    e = html.escape
    cards = [
        f'<li class="podium-card"><span class="podium-place">{e(item["place"])}</span>'
        f'<span class="podium-model">{model_dot(item["model"])}<span>{e(item["model"])}</span></span>'
        f'<span class="podium-crews">{e(item["crews"])}</span>'
        f'<span class="podium-score"><span class="podium-value">{fmt_score(item["score"])}</span>'
        f'<span class="podium-note">{e(item["note"])}</span></span></li>'
        for item in items
    ]
    if not cards:
        return ""
    return f'<ol class="podium" aria-label="{e(label)}">{"".join(cards)}</ol>'

def role_cell(cell, role):
    title = ROLE_TITLE[role][:-1]
    if cell is None:
        return (
            f'<td class="num role-cell is-missing" data-label="{title}"><span class="role-index">—</span>'
            '<span class="role-sub">not ranked</span></td>'
        )
    tone = "is-better" if cell["index"] >= 100 else "is-worse"
    return (
        f'<td class="num role-cell" data-label="{title}"><span class="role-v">'
        f'<span class="role-index {tone}">{fmt_score(cell["index"])}</span>'
        f'<span class="role-sub">{fmt_score(cell["score"])} · #{cell["place"]} of {cell["of"]}</span></span></td>'
    )

def crews_text(row):
    """A model's crews on one line, each crew named once (``sol: high, effort unknown · luna: low``)."""
    return analytics_page.crew_groups_text(row["crews"])

def overall_board(overall, rule=None):
    """The All-roles index board: the Overall table design over models ranked in two or more roles."""
    e = html.escape
    rule = rule or OVERALL_RULE
    rows = overall["rows"]
    scale = bar_scale([{"score": row["overall"]} for row in rows], 100)
    body = []
    for row in rows:
        body.append(
            f'<tr data-rank="{row["place"]}"><td class="rank" data-label="Rank">{rank_text(row["place"])}</td>'
            f'<th scope="row" data-label="Model"><span class="crew-id"><span class="crew-name">{model_dot(row["model"])}'
            f'{e(row["model"])}</span><span class="crew-model">{e(crews_text(row))}</span></span></th>'
            f'<td class="bar-cell" data-label="Index">{score_bar(row["overall"], 100, scale)}'
            f'<span class="score-num">{fmt_score(row["overall"])}</span></td>'
            + "".join(role_cell(row["cells"][role], role) for role in ROLE_ORDER)
            + f'<td class="num units-num" data-label="Work units">{fmt_count(row["units"])}</td></tr>'
        )
    total = sum(weight for _role, weight in rule["weights"]) or 1
    segments = "".join(
        f'<span class="w-{role}" style="flex:{weight} 1 0"></span>' for role, weight in rule["weights"]
    )
    if body:
        table = (
            '<div class="table"><table class="bar-table overall-table"><caption class="sr-only">Models ranked by the '
            'weighted index of the role scores they hold</caption><thead><tr><th class="rank" scope="col">#</th>'
            '<th scope="col">Model</th><th scope="col">Index</th><th class="num" scope="col">Implementer</th>'
            '<th class="num" scope="col">Reviewer</th><th class="num" scope="col">Pilot</th>'
            f'<th class="num" scope="col">Work units</th></tr></thead><tbody>{"".join(body)}</tbody></table></div>'
        )
    else:
        table = '<p class="empty">No model is ranked in two or more roles in this snapshot.</p>'
    one_role = ""
    if overall["one_role"]:
        names = [f"{model} ({ROLE_NOUN[role]})" for model, role in overall["one_role"]]
        one_role = (
            f'<p class="board-note one-role">In one role only, not ranked: {e(join_words(names))}.</p>'
        )
    weights_label = ", ".join(
        f"{ROLE_NOUN[role]} {round(weight / total * 100)}%" for role, weight in rule["weights"]
    )
    return f'''<section class="board overall-board" id="all-roles" aria-labelledby="all-roles-title">
<h2 id="all-roles-title">All-roles index</h2>
<p class="board-note differs">Who contributes most across implementing, reviewing and piloting. Unlike Model rank, which judges implementation alone from Orbit's rank board, it weighs each model's crew scores in every role it holds.</p>
<p class="board-note score-key">{e(overall_rule_text(rule))}</p>
<div class="weight-bar" role="img" aria-label="Weights: {e(weights_label)}">{segments}</div>
{table}
<ul class="legend rank-legend"><li><i class="k-above" aria-hidden="true"></i>above average</li>
<li><i class="k-below" aria-hidden="true"></i>below average</li>
<li><span class="k-fleet" aria-hidden="true"></span> fleet average, 100</li>
<li>Role cells: index, then the role score and the model's place in that role.</li></ul>
{one_role}
</section>'''

def gate_progress(row, rules):
    """(fraction, text) toward the rank board's evidence gate.

    The text is Orbit's own not-eligible reason from rank.json; only a row
    without one falls back to the progress the board's rules imply.
    """
    fraction, text = gate_fraction(row, rules)
    reason = row.get("ineligible_reason")
    return fraction, reason if isinstance(reason, str) and reason else text

def gate_fraction(row, rules):
    min_tasks = rules.get("min_tasks") if as_number(rules.get("min_tasks")) else None
    min_tiers = rules.get("min_tiers") if as_number(rules.get("min_tiers")) else None
    min_tier_tasks = rules.get("min_tier_tasks") if as_number(rules.get("min_tier_tasks")) else None
    units = row["units"]
    if min_tasks and units < min_tasks:
        return units / min_tasks, f"{fmt_count(units)} of {fmt_count(min_tasks)} tasks"
    if min_tiers and min_tier_tasks:
        by_tier = row.get("tasks_by_tier") or {}
        tiers = sum(1 for tier in RANK_TIERS if as_number(by_tier.get(tier)) and by_tier[tier] >= min_tier_tasks)
        if tiers < min_tiers:
            return tiers / min_tiers, f"{tiers} of {fmt_count(min_tiers)} tiers with {fmt_count(min_tier_tasks)}+ tasks"
    return 1.0, "not ranked"

def eligibility_rule(rank):
    """Orbit's eligibility rule as rank.json states it.

    Snapshots before ORB-23668 carry only the numeric rules; the sentence is
    then stated from those numbers, so it follows Orbit's rule either way.
    """
    stated = rank.get("eligibility_rule")
    if isinstance(stated, str) and stated.strip():
        return stated.strip()
    rules = rank.get("rules") or {}
    if not as_number(rules.get("min_tasks")):
        return None
    sentence = f'At least {fmt_count(rules["min_tasks"])} implemented tasks'
    tiers, per_tier = rules.get("min_tiers"), rules.get("min_tier_tasks")
    if as_number(tiers) and as_number(per_tier):
        if tiers == 1:
            sentence += f", with at least {fmt_count(per_tier)} in one assessed tier"
        else:
            sentence += f" spanning at least {fmt_count(tiers)} assessed tiers with at least {fmt_count(per_tier)} tasks each"
    return sentence + "."

def money(value):
    return f"${value:,.2f}" if as_number(value) else "—"

def percent(value, places=1):
    return f"{value * 100:.{places}f}%" if as_number(value) else "—"

def whisker_axis(ranked):
    # Bound observed scores/intervals to the score median +/- max(75, 3 * IQR),
    # using inclusive quartiles. The 75-point floor keeps broad ordinary
    # intervals visible; a distant score or interval cannot flatten the bulk.
    # Include fleet 100, then round outward to tens with 5 points of padding.
    scores = [row["score"] for row in ranked if as_number(row.get("score"))]
    center = statistics.median(scores) if scores else 100.0
    quartiles = statistics.quantiles(scores, n=4, method="inclusive") if len(scores) > 1 else [center] * 3
    radius = max(75, 3 * (quartiles[2] - quartiles[0]))
    values = [100.0]
    for row in ranked:
        interval = row.get("interval") or {}
        for value in (interval.get("p10"), interval.get("p90"), row.get("score")):
            if as_number(value):
                values.append(max(center - radius, min(center + radius, value)))
    low = math.floor(min(values) / 10) * 10 - 5
    high = math.ceil(max(values) / 10) * 10 + 5
    # Round steps, anchored at fleet 100 so even a step above 100 retains it.
    # Budget label widths for the CSS axis minimum (240px), including a gap.
    magnitude = 10
    while True:
        for factor in (1, 2, 2.5, 5):
            step = int(magnitude * factor)
            if step < (high - low) / 6:
                continue
            ticks = list(range(100 + math.ceil((low - 100) / step) * step, int(high) + 1, step))
            label_width = max(len(whisker_tick_label(tick)) for tick in ticks) * 6.5
            if len(ticks) <= 7 and step / (high - low) * 240 >= label_width + 12:
                return low, high, ticks
        magnitude *= 10

def whisker_tick_label(tick):
    return f"{tick:.3g}" if abs(tick) >= 10000 else str(tick)

def axis_pct(value, low, high):
    return max(0.0, min(100.0, (value - low) / (high - low) * 100))

def tier_mix(row):
    e = html.escape
    by_tier = row.get("tasks_by_tier") or {}
    total = sum(by_tier.get(tier, 0) for tier in RANK_TIERS if as_number(by_tier.get(tier)))
    if not total:
        return '<span class="mix-track" aria-hidden="true"></span>'
    parts = []
    words = []
    for tier in RANK_TIERS:
        count = by_tier.get(tier)
        if not as_number(count) or count <= 0:
            continue
        parts.append(f'<span class="mix-{tier}" style="flex:0 0 {count / total * 100:.2f}%" title="{TIER_LABELS[tier]} {fmt_count(count)}"></span>')
        words.append(f"{TIER_LABELS[tier].lower()} {fmt_count(count)}")
    return (
        f'<span class="mix-track" aria-hidden="true">{"".join(parts)}</span>'
        f'<span class="sr-only">tier mix: {e(", ".join(words))}</span>'
    )

def model_detail(row, rank):
    e = html.escape
    rules = rank.get("rules") or {}
    measures = []
    for measure in rank.get("measures") or []:
        if not isinstance(measure, dict) or not isinstance(measure.get("key"), str):
            continue
        entry = (row.get("measures") or {}).get(measure["key"]) or {}
        value = entry.get("contribution")
        on = as_number(value)
        width = min(abs(value), 25) / 25 * 50 if on else 0
        side = "is-better" if on and value >= 0 else "is-worse"
        bar = (
            f'<span class="contrib-bar {side}" style="width:{width:.1f}%"></span>' if on else ""
        )
        reason = entry.get("reason") or measure.get("reason") or ""
        shown = (("+" if value > 0 else "") + f"{value:.2f}").replace("-", "−") if on else "not yet"
        weight = fmt_num(measure.get("weight")) or "—"
        measures.append(
            f'<li class="contrib{"" if on else " is-missing"}"><span class="contrib-label">{e(measure.get("label") or measure["key"])}</span>'
            f'<span class="contrib-weight" title="weight">{e(weight)}</span>'
            f'<span class="contrib-plot" aria-hidden="true"><span class="contrib-axis"></span>{bar}</span>'
            f'<span class="contrib-value {side if on else ""}"{f" title={chr(34)}{e(reason)}{chr(34)}" if reason and not on else ""}>{e(shown)}</span></li>'
        )
    k = fmt_num(rules.get("shrinkage_k"))
    raw = row.get("raw_score")
    shrink = (
        f'<p class="detail-note">Raw {fmt_score(raw)}, shrunk to {fmt_score(row.get("score"))} toward 100'
        + (f" (k = {k})" if k else "") + ".</p>"
        if as_number(raw) else ""
    )
    interval = row.get("interval") or {}
    interval_text = (
        f'<p class="detail-note">p10–p90 interval: {fmt_score(interval["p10"])} to {fmt_score(interval["p90"])}.</p>'
        if as_number(interval.get("p10")) and as_number(interval.get("p90")) else ""
    )
    min_tier_tasks = rules.get("min_tier_tasks") if as_number(rules.get("min_tier_tasks")) else 0
    tier_rows = []
    for tier in row.get("tiers") or []:
        if not isinstance(tier, dict) or tier.get("tier") not in TIER_LABELS:
            continue
        tasks = tier.get("tasks")
        thin = as_number(tasks) and tasks < min_tier_tasks
        tier_rows.append(
            f'<tr{" class=" + chr(34) + "dim" + chr(34) if thin else ""}><th scope="row" data-label="Tier">'
            f'<span class="mix-swatch mix-{tier["tier"]}" aria-hidden="true"></span>{TIER_LABELS[tier["tier"]]}</th>'
            f'<td class="num" data-label="Tasks">{fmt_count(tasks) or "—"}</td>'
            f'<td class="num" data-label="Score">{fmt_score(tier.get("score"))}</td>'
            f'<td class="num" data-label="$ / task">{money(tier.get("cost_per_task"))}</td></tr>'
        )
    tiers_html = (
        '<div class="table"><table class="mini-table"><caption class="sr-only">By tier</caption><thead><tr>'
        '<th scope="col">Tier</th><th class="num" scope="col">Tasks</th><th class="num" scope="col">Score</th>'
        f'<th class="num" scope="col">$ / task</th></tr></thead><tbody>{"".join(tier_rows)}</tbody></table></div>'
        + (f'<p class="detail-note">Faded tiers have under {fmt_count(min_tier_tasks)} tasks.</p>' if min_tier_tasks else "")
        if tier_rows else '<p class="detail-note">No tier breakdown.</p>'
    )
    cost = row.get("cost") or {}
    landed = row.get("landed_tasks")
    landed_text = (
        f'{fmt_count(landed)} / {fmt_count(row["units"])} · {percent(row.get("landed_rate"))}'
        if as_number(landed) else percent(row.get("landed_rate"))
    )
    crews = " · ".join(
        f'{item["label"]} {fmt_count(item["tasks"])}' for item in rank_crew_entries(row) if item["tasks"] is not None
    ) or "—"
    delivery = (
        '<dl class="facts">'
        f'<div><dt>Landed</dt><dd>{e(landed_text)}</dd></div>'
        f'<div><dt>Crews</dt><dd>{e(crews)}</dd></div>'
        f'<div><dt>Expected $ / task</dt><dd>{money(cost.get("expected_per_task"))}</dd></div>'
        f'<div><dt>Cost coverage</dt><dd>{percent(cost.get("coverage"), 0)}</dd></div>'
        '</dl>'
    )
    return (
        '<div class="model-detail">'
        f'<div class="detail-col"><h4>Score contributions <span class="detail-key">weight · vs. tier expectation</span></h4>'
        f'<ul class="contribs">{"".join(measures)}</ul>{shrink}{interval_text}</div>'
        f'<div class="detail-col"><h4>By tier</h4>{tiers_html}</div>'
        f'<div class="detail-col"><h4>Delivery</h4>{delivery}</div>'
        '</div>'
    )

def rank_publishes_places(rank):
    """Whether this snapshot may show rank numbers, bands and a podium.

    A live snapshot keeps the places it was published with and is labelled
    provisional. A settled board from before scales were recorded keeps its
    places unless it is unqualified. A settled board publishes places only
    from a calibrated season (``scales_source`` ``season``) that has qualified.
    """
    if not isinstance(rank, dict):
        return False
    if rank.get("live") is True:
        return True
    source = rank.get("scales_source")
    if source is None:
        return rank.get("qualified") is not False
    return source == "season" and rank.get("qualified") is True

def rank_withheld_reason(rank):
    """Why a settled board shows scores and intervals without ranks or a podium."""
    parts = []
    if rank.get("scales_source") == "window_estimate":
        parts.append("the noise scales are estimated from this window, not frozen for a calibrated season")
    if rank.get("qualified") is False:
        parts.append("the board has not qualified")
    if not parts:
        return None
    because = parts[0] if len(parts) == 1 else f"{parts[0]}, and {parts[1]}"
    return (
        "No ranking is published: "
        + because
        + ", so scores and intervals are shown without ranks or a podium."
    )

def settle_lag_text(rank):
    lag = rank.get("settle_lag") if isinstance(rank.get("settle_lag"), str) else "14d"
    if lag.endswith("d") and lag[:-1].isdigit():
        count = int(lag[:-1])
        return "1 day" if count == 1 else f"{count} days"
    return lag
