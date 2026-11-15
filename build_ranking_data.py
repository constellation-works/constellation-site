"""Ranking scorecard data helpers (split from build.py)."""

import html
import json
import math
import pathlib
import sys
from build_common import as_number, fmt_count, friendly_window, gap_identity, join_words, lower_first, plural


TIER_ORDER = ("low", "medium", "hard", "xhard")

TIER_LABELS = {"low": "Low", "medium": "Medium", "hard": "Hard", "xhard": "Extra hard"}

TIER_SCORE_KEY = (
    "Score: tier crew score per 100 tasks, support summed across task types, "
    "against the fleet's rates on this tier; 100 is the fleet average."
)

def load_scorecards(directory):
    path = pathlib.Path(directory) / "scorecards.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"{path}: invalid JSON ({exc})")
    if not isinstance(data, dict):
        sys.exit(f"{path}: expected an object")
    return data

def require_text(board, key, name):
    value = board.get(key)
    if not isinstance(value, str) or not value.strip():
        sys.exit(f"scorecards.json: {name} is missing {key}")
    return " ".join(value.split())

def board_min_support(board, name):
    value = board.get("min_support")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        sys.exit(f"scorecards.json: {name} is missing min_support")
    return value

def board_window(board, name):
    window = board.get("window")
    if not isinstance(window, dict):
        sys.exit(f"scorecards.json: {name} is missing its UTC window")
    since, until, key = window.get("since"), window.get("until"), window.get("key")
    if not isinstance(since, str) or not since or not isinstance(until, str) or not until:
        sys.exit(f"scorecards.json: {name} is missing its UTC window")
    if key != "30d":
        sys.exit(f"scorecards.json: {name} must be a 30d window, got {key!r}")
    return since, until

def effort_text(row):
    """A row's effort identity: its effort label, or None.

    Scorecards split a crew's rows by recorded reasoning effort, so the effort
    is part of the row's identity (``effort unknown`` when unrecorded). A
    snapshot written before the split carries neither field and its crews
    render as before.
    """
    label = row.get("effort_label")
    if isinstance(label, str) and label.strip():
        return " ".join(label.split())
    effort = row.get("reasoning_effort")
    if isinstance(effort, str) and effort.strip():
        return "effort unknown" if effort == "unknown" else effort
    return None

def crew_view(row):
    """How a crew row is named: ``crew@effort`` on every board.

    - a crew name that already carries its effort (``haiku@high``) is shown as is;
    - a plain crew gets its recorded effort appended (``sol@high``);
    - an unrecorded effort reads ``effort unknown`` after the crew name.

    Effort is never read from crew configuration, so a snapshot's
    ``effort_estimate`` (written before ORB-23846) is ignored. Returns the
    identity effort plus (base, suffix); a snapshot without effort fields
    keeps the bare crew name, as before.
    """
    crew = row["crew"]
    effort = effort_text(row)
    view = {"effort": effort, "base": crew, "suffix": ""}
    if effort is None:
        return view
    if "@" in crew:
        base, _sep, tail = crew.partition("@")
        view.update(base=base, suffix=f"@{tail}")
        return view
    recorded = row.get("reasoning_effort")
    if isinstance(recorded, str) and recorded.strip() and recorded != "unknown":
        view["suffix"] = f"@{recorded}"
    else:
        view["suffix"] = f" · {effort}"  # "effort unknown", or recorded as something other than an effort
    return view

def crew_key(row):
    """A crew row's identity on a board: crew, model and effort."""
    return (row["crew"], row["model"], row.get("effort"))

def crew_label(row):
    """Plain-text crew name with its effort, e.g. ``sol@high`` or ``sol · effort unknown``."""
    if "base" not in row:
        return row["crew"]
    return row["base"] + row["suffix"]

def crew_name_html(row):
    """The crew name with its effort beside it in the secondary style, on one line."""
    e = html.escape
    if "base" not in row or not row["suffix"]:
        return e(row["crew"])
    return f'{e(row["base"])}<span class="crew-effort">{e(row["suffix"])}</span>'

def display_rows(board, name):
    """Rows safe to publish: gaps removed, and thin rows left unranked."""
    unit = require_text(board, "unit", name)
    min_support = board_min_support(board, name)
    rows_in = board.get("rows")
    if not isinstance(rows_in, list):
        sys.exit(f"scorecards.json: {name} rows are missing")
    rows = []
    for row in rows_in:
        if not isinstance(row, dict):
            continue
        crew, model = row.get("crew"), row.get("model")
        if not isinstance(crew, str) or not isinstance(model, str) or gap_identity(crew, model):
            continue
        units = row.get("units")
        if not as_number(units):
            continue
        below = bool(row.get("below_support")) or bool(row.get("unjudged")) or units < min_support
        rank = row.get("rank")
        if below or isinstance(rank, bool) or not isinstance(rank, int):
            rank = None
        rows.append({
            "crew": crew,
            "model": model,
            **crew_view(row),
            "units": units,
            "rank": rank,
            "score": row.get("score") if as_number(row.get("score")) else None,
        })
    ranked = sorted((row for row in rows if row["rank"] is not None), key=lambda row: row["rank"])
    rest = sorted(
        (row for row in rows if row["rank"] is None),
        key=lambda row: (
            -(row["score"] if row["score"] is not None else float("-inf")),
            -row["units"],
            row["crew"],
            row["model"],
            row["effort"] or "",
        ),
    )
    return {
        "unit": unit,
        "min_support": min_support,
        "rows": ranked + rest,
        "window": board_window(board, name),
        "score_key": require_text(board, "score_key", name),
    }

def board_terms(board):
    """The board's published score terms: key, label and credit or debit group."""
    terms = []
    for term in board.get("terms") or []:
        if not isinstance(term, dict):
            continue
        key, label, group = term.get("key"), term.get("label"), term.get("group")
        if not isinstance(key, str) or not isinstance(label, str) or group not in ("credit", "problem"):
            continue
        weight = term.get("weight")
        terms.append({
            "key": key,
            "label": " ".join(label.split()),
            "group": group,
            "weight": weight if as_number(weight) else None,
        })
    return terms

def fleet_average(board):
    value = board.get("fleet_average")
    return value if as_number(value) else None

def fmt_score(value):
    """One decimal with a true minus sign; scores can go below zero."""
    if not as_number(value):
        return "—"
    text = f"{value:.1f}"
    return text.replace("-", "−") if text.startswith("-") else text

def tier_slots(block):
    """Implementer tier cells aggregated per (tier, crew, model).

    A crew's tier support is the sum of its task-type cells and its tier score
    is the tier crew score (``crew_mean``), the same for every type. Crews keep
    their model and effort in the key, as the overall board does, so a second
    model run under the same crew name (luna on gpt-6.1-luna), or the same
    model at another effort, is its own row rather than adding to the main row. Each tier is ranked separately; a slot
    under ``min_support`` stays unranked.
    """
    name = "implementers by tier"
    require_text(block, "unit", name)
    min_support = board_min_support(block, name)
    cells = block.get("cells")
    if not isinstance(cells, list):
        sys.exit("scorecards.json: implementers by tier cells are missing")
    grouped = {tier: {} for tier in TIER_ORDER}
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        tier = cell.get("tier")
        if tier not in grouped:
            continue
        crew, model = cell.get("crew"), cell.get("model")
        if not isinstance(crew, str) or not isinstance(model, str) or gap_identity(crew, model):
            continue
        count = cell.get("n")
        if not as_number(count) or count <= 0:
            continue
        view = crew_view(cell)
        slot = grouped[tier].setdefault(
            (crew, model, view["effort"]),
            {"crew": crew, "model": model, **view, "tier": tier, "units": 0, "score": None, "rank": None},
        )
        slot["units"] += count
        if slot["score"] is None and as_number(cell.get("crew_mean")):
            slot["score"] = cell["crew_mean"]
    for tier, slots in grouped.items():
        for key in [key for key, slot in slots.items() if slot["score"] is None]:
            del slots[key]
        ranked = sorted(
            (slot for slot in slots.values() if slot["units"] >= min_support),
            key=lambda slot: (-slot["score"], -slot["units"], slot["crew"], slot["model"], slot["effort"] or ""),
        )
        for index, slot in enumerate(ranked, 1):
            slot["rank"] = index
    return grouped, min_support

def term_extremes(rows, terms):
    """Best and worst per-100 rate for each term among ranked crews.

    Credit terms are best when high, debit terms when low. A term where every
    ranked crew has the same rate (or only one is measured) flags nothing.
    """
    extremes = {}
    ranked = [row for row in rows if row["rank"] is not None]
    for term in terms:
        values = [row["per_100"].get(term["key"]) for row in ranked]
        values = [value for value in values if value is not None]
        if len(set(values)) < 2:
            continue
        high, low = max(values), min(values)
        if term["group"] == "credit":
            extremes[term["key"]] = (high, low)
        else:
            extremes[term["key"]] = (low, high)
    return extremes

def per_100_rates(row, terms):
    per_100 = row.get("per_100")
    rates = {}
    for term in terms:
        value = per_100.get(term["key"]) if isinstance(per_100, dict) else None
        rates[term["key"]] = value if as_number(value) else None
    return rates

def role_rows(board, name):
    """display_rows plus each published row's per-100 term rates."""
    shown = display_rows(board, name)
    terms = board_terms(board)
    by_identity = {}
    for row in board.get("rows") or []:
        if isinstance(row, dict) and isinstance(row.get("crew"), str) and isinstance(row.get("model"), str):
            by_identity.setdefault((row["crew"], row["model"], effort_text(row)), row)
    for row in shown["rows"]:
        row["per_100"] = per_100_rates(by_identity.get(crew_key(row), {}), terms)
    shown["terms"] = terms
    shown["fleet"] = fleet_average(board)
    return shown

def bar_scale(rows, fleet):
    """A round upper bound for the score bars: the next multiple of 20."""
    values = [row["score"] for row in rows if row["score"] is not None]
    if fleet is not None:
        values.append(fleet)
    top = max(values, default=0)
    return max(20, math.ceil(top / 20) * 20)

def score_bar(score, fleet, scale):
    """A bar from 0 to the score, coloured against the fleet average, with its marker."""
    width = 0.0 if score is None else max(0.0, min(100.0, score / scale * 100))
    if score is None or fleet is None:
        tone = "is-neutral"
    else:
        tone = "is-better" if score >= fleet else "is-worse"
    marker = (
        f'<span class="fleet-mark" style="left:{min(100.0, fleet / scale * 100):.1f}%"></span>'
        if fleet is not None and fleet > 0 else ""
    )
    return (
        f'<span class="score-bar" aria-hidden="true">'
        f'<span class="score-fill {tone}" style="width:{max(width, 0.5):.1f}%"></span>{marker}</span>'
    )

def score_key_line(unit, fleet, extra=""):
    e = html.escape
    parts = [f"Per 100 {e(unit)}"]
    if fleet is not None:
        parts.append(
            f'<span class="k-fleet" aria-hidden="true"></span> fleet average {fmt_score(fleet)}'
            ' · <span class="is-better">above</span> / <span class="is-worse">below</span> average'
        )
    if extra:
        parts.append(extra)
    return f'<p class="board-key">{" · ".join(parts)}</p>'

def board_window_line(since, until, prefix="Window"):
    e = html.escape
    return (
        f'<p class="board-window">{e(prefix)} {friendly_window(since, until)}. '
        f'<span class="window-exact">Exact: <time datetime="{e(since)}">{e(since)}</time>'
        f' to <time datetime="{e(until)}">{e(until)}</time> UTC.</span></p>'
    )

def implementer_takeaways(slots, rows, terms, unit):
    """Takeaway cards derived from the tier slots and the overall breakdown.

    One card per run of adjacent tiers led by the same crew (leader and
    runner-up for a single tier), then a watch card for the weakest tier cell
    with enough support, with that crew's weakest overall term.
    """
    e = html.escape
    leaders = []
    for tier in TIER_ORDER:
        ranked = sorted((s for s in slots[tier].values() if s["rank"] is not None), key=lambda s: s["rank"])
        if ranked:
            leaders.append((tier, ranked))
    groups = []
    for tier, ranked in leaders:
        key = crew_key(ranked[0])
        if groups and groups[-1]["key"] == key:
            groups[-1]["tiers"].append((tier, ranked))
        else:
            groups.append({"key": key, "tiers": [(tier, ranked)]})
    cards = []
    for group in groups:
        tiers = group["tiers"]
        names = [TIER_LABELS[tier] for tier, _ranked in tiers]
        label = join_words([names[0]] + [lower_first(name) for name in names[1:]])
        crew = crew_name_html(tiers[0][1][0])
        if len(tiers) > 1:
            count = "both" if len(tiers) == 2 else f"all {len(tiers)}"
            head = f"{crew} leads {count} tiers"
            sub = " · ".join(
                f'{fmt_score(ranked[0]["score"])} on {fmt_count(ranked[0]["units"])}'
                + (f" {TIER_LABELS[tier].lower()} {unit}" if index == 0 else f" {TIER_LABELS[tier].lower()}")
                for index, (tier, ranked) in enumerate(tiers)
            )
        else:
            tier, ranked = tiers[0]
            lead = ranked[0]
            tier_word = TIER_LABELS[tier].lower()
            if len(ranked) > 1:
                second = ranked[1]
                head = f'{crew} {fmt_score(lead["score"])}, {crew_name_html(second)} {fmt_score(second["score"])}'
                sub = f'{fmt_count(lead["units"])} vs {fmt_count(second["units"])} {tier_word} {unit}'
            else:
                head = f'{crew} {fmt_score(lead["score"])}'
                sub = f'{fmt_count(lead["units"])} {tier_word} {unit} · the only ranked crew'
        cards.append((label, head, sub))
    sizeable = [s for tier in TIER_ORDER for s in slots[tier].values() if s["rank"] is not None]
    if sizeable:
        weakest = min(sizeable, key=lambda s: (s["score"], -s["units"], s["crew"], s["effort"] or ""))
        if weakest["score"] < 100:
            tier_word = TIER_LABELS[weakest["tier"]].lower()
            head = f'{crew_name_html(weakest)} {fmt_score(weakest["score"])} on {e(tier_word)}'
            sub = f'{fmt_count(weakest["units"])} {tier_word} {unit}'
            note = weakest_term(rows, terms, crew_key(weakest))
            if note:
                sub += f" · {note}"
            cards.append(("Watch", head, sub))
    if not cards:
        return ""
    # Heads are HTML: crew names come from crew_name_html, the rest is numbers.
    items = "".join(
        f'<li><div class="tile takeaway"><span class="tile-head">{e(label)}</span>'
        f'<span class="takeaway-head">{head}</span><span class="tile-sub">{e(sub)}</span></div></li>'
        for label, head, sub in cards
    )
    return f'<ul class="tiles takeaways" aria-label="Takeaways">{items}</ul>'

def weakest_term(rows, terms, identity):
    """The term where this crew is worst among ranked crews, by weighted gap from their mean."""
    ranked = [row for row in rows if row["rank"] is not None]
    row = next((r for r in ranked if crew_key(r) == identity), None)
    if row is None:
        return ""
    extremes = term_extremes(rows, terms)
    best = None
    for term in terms:
        value = row["per_100"].get(term["key"])
        if value is None or term["key"] not in extremes or value != extremes[term["key"]][1]:
            continue
        values = [r["per_100"][term["key"]] for r in ranked if r["per_100"].get(term["key"]) is not None]
        gap = abs(value - sum(values) / len(values)) * abs(term["weight"] if term["weight"] is not None else 1)
        if best is None or gap > best[0]:
            best = (gap, term, value)
    if best is None:
        return ""
    _gap, term, value = best
    return f'{fmt_score(value)} {lower_first(term["label"])} per 100 overall, the {"lowest" if term["group"] == "credit" else "highest"} of ranked crews'

def crew_cell(row):
    e = html.escape
    return (
        f'<span class="crew-id"><span class="crew-name">{crew_name_html(row)}</span>'
        f'<span class="crew-model">{e(row["model"])}</span></span>'
    )

def rank_text(rank):
    if rank is None:
        return '<span aria-hidden="true">–</span><span class="sr-only">unranked</span>'
    return f'<span class="sr-only">Rank </span>{rank}'

def term_breakdown(row, terms, extremes, unit):
    e = html.escape
    tiles = []
    for term in terms:
        value = row["per_100"].get(term["key"])
        kind = "credit" if term["group"] == "credit" else "debit"
        note, tone = "", ""
        if value is None:
            note = "not measured for this crew"
            tone = " is-missing"
        elif term["key"] in extremes:
            best, worst = extremes[term["key"]]
            if row["rank"] is not None and value == best:
                note, tone = "best of ranked crews", " is-better"
            elif row["rank"] is not None and value == worst:
                note, tone = "worst of ranked crews", " is-worse"
        shown = "—" if value is None else fmt_score(value)
        tiles.append(
            f'<li class="term{tone}" data-term="{e(term["key"])}">'
            f'<span class="term-label">{e(term["label"])} <span class="term-kind">· {kind}</span></span>'
            f'<span class="term-value">{e(shown)}</span>'
            f'<span class="term-note">{e(note)}</span></li>'
        )
    if not tiles:
        return '<p class="term-intro">This snapshot publishes no term rates.</p>'
    return (
        f'<p class="term-intro">Rates per 100 {e(unit)}. The score combines these with the published '
        'weights, then shrinks small samples toward the fleet.</p>'
        f'<ul class="terms">{"".join(tiles)}</ul>'
    )

def implementers_overall(shown):
    e = html.escape
    unit = shown["unit"]
    fleet = shown["fleet"]
    ranked = [row for row in shown["rows"] if row["rank"] is not None]
    unranked = [row for row in shown["rows"] if row["rank"] is None]
    scale = bar_scale(ranked, fleet)
    extremes = term_extremes(shown["rows"], shown["terms"])
    since, until = shown["window"]
    items = []
    for row in ranked:
        items.append(
            f'<li><details class="crew-row" data-rank="{row["rank"]}">'
            '<summary class="bar-row">'
            f'<span class="rank">{rank_text(row["rank"])}</span>'
            f'{crew_cell(row)}'
            f'{score_bar(row["score"], fleet, scale)}'
            f'<span class="score-num">{fmt_score(row["score"])}<span class="sr-only"> per 100 {e(unit)}</span></span>'
            f'<span class="units-num">{fmt_count(row["units"])}<span class="sr-only"> {e(unit)}</span></span>'
            '</summary>'
            f'<div class="crew-detail">{term_breakdown(row, shown["terms"], extremes, unit)}</div>'
            '</details></li>'
        )
    if items:
        head = (
            '<div class="bar-row bar-head" aria-hidden="true"><span>Rank</span><span>Crew</span>'
            '<span>Score</span><span class="num">Score</span><span class="num">Tasks</span></div>'
        )
        ranking = f'<div class="rank-list">{head}<ol>{"".join(items)}</ol></div>'
    else:
        ranking = '<p class="empty">No ranked crews in this window.</p>'
    folded = ""
    if unranked:
        rows_html = "".join(
            f'<tr data-rank="unranked"><td data-label="Rank" class="rank unranked">{rank_text(None)}</td>'
            f'<td data-label="Crew">{crew_name_html(row)}</td>'
            f'<td data-label="Model" class="crew-model">{e(row["model"])}</td>'
            f'<td data-label="Score" class="num">{fmt_score(row["score"]) if row["score"] is not None else "unjudged"}</td>'
            f'<td data-label="{e(unit.capitalize())}" class="num">{fmt_count(row["units"])}</td></tr>'
            for row in unranked
        )
        scored = [row["score"] for row in unranked if row["score"] is not None]
        sizes = [row["units"] for row in unranked]
        swing = ""
        if len(scored) > 1:
            low_n, high_n = fmt_count(min(sizes)), fmt_count(max(sizes))
            span = low_n if low_n == high_n else f"{low_n}–{high_n}"
            swing = (
                f'<p class="board-note">Scores on {span} {e(unit)} swing widely '
                f'({fmt_score(min(scored))} to {fmt_score(max(scored))}) and say little about the crew.</p>'
            )
        count = len(unranked)
        folded = (
            f'<details class="more unranked-crews"><summary>{count} {plural(count, "crew")} under '
            f'{shown["min_support"]} {e(unit)}, not ranked</summary>'
            '<div class="table"><table><caption class="sr-only">Implementers below minimum support</caption>'
            '<thead><tr><th class="rank">Rank</th><th>Crew</th><th>Model</th><th class="num">Score</th>'
            f'<th class="num">{e(unit.capitalize())}</th></tr></thead>'
            f'<tbody>{rows_html}</tbody></table></div>{swing}</details>'
        )
    return f'''<section class="board" id="implementer-crews" aria-labelledby="implementer-crews-title">
<div class="board-head"><h3 id="implementer-crews-title">Implementer crews</h3>
{score_key_line(unit, fleet, "select a crew for its breakdown" if items else "")}</div>
{board_window_line(since, until)}
<p class="score-key">{e(shown["score_key"])}</p>
{ranking}
<p class="support-note">Rows under {shown["min_support"]} {e(unit)} stay unranked.</p>
{folded}
</section>'''

def heat_class(score):
    """Five shades around the tier's fleet rate of 100."""
    delta = score - 100
    if delta >= 25:
        return "hm-b2"
    if delta >= 5:
        return "hm-b1"
    if delta > -5:
        return "hm-0"
    if delta > -25:
        return "hm-w1"
    return "hm-w2"

def tier_heatmap(block, overall_rows):
    """One crew × tier table from implementers_by_tier.cells.

    Rows follow the overall ranking; crews with tier cells but no overall row
    follow by tier support. Crews with no tier slot at or above min_support and
    no overall rank fold into a disclosure.
    """
    e = html.escape
    slots, min_support = tier_slots(block)
    unit = require_text(block, "unit", "implementers by tier")
    since, until = board_window(block, "implementers by tier")
    identities = {}
    for tier in TIER_ORDER:
        for key, slot in slots[tier].items():
            identities.setdefault(key, {
                **{name: slot[name] for name in ("crew", "model", "effort", "base", "suffix")},
                "units": 0, "sized": False,
            })
            identities[key]["units"] += slot["units"]
            identities[key]["sized"] = identities[key]["sized"] or slot["rank"] is not None
    order = {crew_key(row): index for index, row in enumerate(overall_rows)}
    ranked_overall = {crew_key(row) for row in overall_rows if row["rank"] is not None}
    keys = sorted(
        identities,
        key=lambda key: (order.get(key, len(order)), -identities[key]["units"], key[0], key[1], key[2] or ""),
    )
    main = [key for key in keys if key in ranked_overall or identities[key]["sized"]]
    rest = [key for key in keys if key not in main]
    tiers = [tier for tier in TIER_ORDER if slots[tier]]

    def render_row(key):
        ident = identities[key]
        cells = []
        for tier in tiers:
            label = TIER_LABELS[tier]
            slot = slots[tier].get(key)
            if slot is None:
                cells.append(f'<td data-label="{label}" class="hm hm-none"><span class="hm-v">'
                             '<span class="hm-score">–</span><span class="hm-sub">no tasks</span></span></td>')
                continue
            thin = slot["rank"] is None
            star = '<span class="hm-star" aria-hidden="true">★ </span>' if slot["rank"] == 1 else ""
            star_sr = '<span class="sr-only">, best ranked crew in this tier</span>' if slot["rank"] == 1 else ""
            sub = f'{fmt_count(slot["units"])} {unit if slot["units"] != 1 else unit.rstrip("s")}'
            if thin:
                sub += " · unranked"
            cells.append(
                f'<td data-label="{label}" class="hm {heat_class(slot["score"])}{" is-thin" if thin else ""}"'
                f' data-rank="{slot["rank"] if slot["rank"] is not None else "unranked"}">'
                f'<span class="hm-v"><span class="hm-score">{star}{fmt_score(slot["score"])}{star_sr}</span>'
                f'<span class="hm-sub">{e(sub)}</span></span></td>'
            )
        return (
            f'<tr><th scope="row">{crew_cell(ident)}</th>{"".join(cells)}</tr>'
        )

    def render_table(part, caption, head_ids):
        heads = "".join(
            (f'<th scope="col" id="implementers-{tier}">' if head_ids else '<th scope="col">')
            + f"{TIER_LABELS[tier]}</th>"
            for tier in tiers
        )
        return (
            f'<div class="table heatmap-wrap"><table class="heatmap"><caption class="sr-only">{e(caption)}</caption>'
            f'<thead><tr><th scope="col">Crew</th>{heads}</tr></thead>'
            f'<tbody>{"".join(render_row(key) for key in part)}</tbody></table></div>'
        )

    if main:
        body = render_table(main, "Implementer tier scores by crew; 100 is each tier's fleet rate", True)
    else:
        body = '<p class="empty">No tier cells in this window.</p>'
    if rest:
        count = len(rest)
        body += (
            f'<details class="more"><summary>{count} more {plural(count, "crew")} with only small tier samples</summary>'
            + render_table(rest, "Crews with only small tier samples", False) + "</details>"
        )
    legend = (
        '<div class="hm-legend" aria-hidden="true"><span>Below 100</span>'
        '<span class="hm-swatches"><i class="hm-w2"></i><i class="hm-w1"></i><i class="hm-0"></i>'
        '<i class="hm-b1"></i><i class="hm-b2"></i></span><span>Above 100</span></div>'
    )
    # Old per-tier board anchors stay valid: a column header when the tier has
    # a column, otherwise an empty marker at the top of the section.
    with_column = set(tiers) if main else set()
    anchors = "".join(f'<span id="implementers-{tier}"></span>' for tier in TIER_ORDER if tier not in with_column)
    return f'''<section class="board" id="tiers" aria-labelledby="tiers-title">{anchors}
<div class="board-head"><h3 id="tiers-title">Implementers by tier</h3>
<p class="board-key">Each tier's fleet rate is 100. ★ marks the best ranked crew in a tier; faded cells have under {min_support} {e(unit)} and stay unranked.</p></div>
{body}
{legend}
<div class="hm-foot">{board_window_line(since, until)}
<p class="score-key">{e(TIER_SCORE_KEY)}</p>
</div>
</section>''', slots

def role_bar_board(shown, element_id, title, label=None, note_html="", columns=(), footer="", key_note=""):
    """A reviewer or pilot board: score bars, unranked rows faded in place."""
    e = html.escape
    unit = shown["unit"]
    fleet = shown["fleet"]
    scale = bar_scale(shown["rows"], fleet)
    since, until = shown["window"]
    head_extra = "".join(f'<th class="num" scope="col">{e(name)}</th>' for name, _fn in columns)
    rows = []
    for row in shown["rows"]:
        extra = "".join(f'<td class="num" data-label="{e(name)}">{fn(row)}</td>' for name, fn in columns)
        rank_attr = str(row["rank"]) if row["rank"] is not None else "unranked"
        score = fmt_score(row["score"]) if row["score"] is not None else "unjudged"
        dim = ' class="dim"' if row["rank"] is None else ""
        rows.append(
            f'<tr data-rank="{rank_attr}"{dim}>'
            f'<td data-label="Rank" class="rank{" unranked" if row["rank"] is None else ""}">{rank_text(row["rank"])}</td>'
            f'<th scope="row" data-label="Crew">{crew_cell(row)}</th>'
            f'<td data-label="Score" class="bar-cell">{score_bar(row["score"], fleet, scale)}'
            f'<span class="score-num">{score}<span class="sr-only"> per 100 {e(unit)}</span></span></td>'
            f'{extra}'
            f'<td data-label="{e(unit.capitalize())}" class="num">{fmt_count(row["units"])}</td></tr>'
        )
    if rows:
        table_html = (
            f'<div class="table"><table class="bar-table"><caption class="sr-only">{e(title)}'
            f'{f" ({e(label)})" if label else ""}</caption>'
            f'<thead><tr><th class="rank" scope="col">Rank</th><th scope="col">Crew</th><th scope="col">Score</th>'
            f'{head_extra}<th class="num" scope="col">{e(unit.capitalize())}</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>'
        )
    else:
        table_html = '<p class="empty">No rows in this window.</p>'
    label_html = f' <span class="board-label">{e(label)}</span>' if label else ""
    return f'''<section class="board" id="{e(element_id)}" aria-labelledby="{e(element_id)}-title">
<div class="board-head"><h3 id="{e(element_id)}-title">{e(title)}{label_html}</h3>
{score_key_line(unit, fleet)}</div>
{board_window_line(since, until)}
{note_html}<p class="score-key">{e(shown["score_key"])}{(" " + e(key_note)) if key_note else ""}</p>
{table_html}
<p class="support-note">Rows under {shown["min_support"]} {e(unit)} stay unranked and are faded.</p>
{footer}
</section>'''

def terms_sentence(terms):
    credits = [lower_first(t["label"]) for t in terms if t["group"] == "credit"]
    debits = [lower_first(t["label"]) for t in terms if t["group"] == "problem"]
    parts = []
    if credits:
        parts.append(f"Credit: {join_words(credits)}.")
    if debits:
        parts.append(f"Debits: {join_words(debits)}.")
    return " ".join(parts)

def provisional_note(board):
    count = board.get("provisional_units")
    if not as_number(count) or count <= 0:
        return None
    return f"{fmt_count(count)} reviews in this window are still provisional."

def thin_board_note(shown, what):
    ranked = [row for row in shown["rows"] if row["rank"] is not None]
    if len(ranked) >= 3:
        return None
    count = len(ranked)
    text = (
        f"Only {count} {plural(count, 'crew')} {what} {shown['min_support']} or more {shown['unit']} "
        "in this window, so this board is thin."
    )
    shown_unranked = [row for row in shown["rows"] if row["rank"] is None and row["score"] is not None]
    if shown_unranked:
        names = join_words(f'{crew_label(row)} ({fmt_score(row["score"])})' for row in shown_unranked)
        text += f" {names} {'is' if len(shown_unranked) == 1 else 'are'} shown but not ranked."
    return text

def reviewers_group(reviewers):
    e = html.escape
    provisional = reviewers.get("provisional")
    if not isinstance(provisional, dict):
        sys.exit("scorecards.json: reviewers.provisional is required")
    settled = reviewers.get("settled")
    if settled is not None and not isinstance(settled, dict):
        sys.exit("scorecards.json: reviewers.settled is not a board")
    prov = role_rows(provisional, "reviewers provisional")
    notes = [text for text in (provisional_note(provisional),) if text]
    if notes and settled is not None:
        notes.append("These scores will move as findings are confirmed or rejected; the settled board is the one to trust.")
    thin = thin_board_note(prov, "reviewed")
    if thin:
        notes.append(thin)
    banner = f'<p class="role-banner">{e(" ".join(notes))}</p>\n' if notes else ""
    # The score key above each table is the board's one credit/debit explanation.
    boards = [role_bar_board(prov, "reviewers-provisional", "Reviewer crews", "Provisional", banner)]
    toggle = ""
    if isinstance(settled, dict):
        done = role_rows(settled, "reviewers settled")
        thin = thin_board_note(done, "reviewed")
        prev = "previous window" if done["window"][1] < prov["window"][1] else "its own window"
        settled_banner = f'<p class="role-banner">{e(thin)}</p>\n' if thin else ""
        boards.append(role_bar_board(done, "reviewers-settled", "Reviewer crews", "Settled", settled_banner))
        toggle = (
            '<div class="board-toggle" role="group" aria-label="Review window" hidden>'
            '<button type="button" aria-pressed="true" data-board="reviewers-provisional">Provisional · this window</button>'
            f'<button type="button" aria-pressed="false" data-board="reviewers-settled">Settled · {prev}</button></div>'
        )
    return toggle + "\n".join(boards), prov

def pilots_board(pilots):
    shown = role_rows(pilots, "pilots")
    keys = {term["key"] for term in shown["terms"]}

    def rate(key):
        def cell(row):
            return fmt_score(row["per_100"].get(key)) if row["per_100"].get(key) is not None else "—"
        return cell

    columns = []
    shown_keys = set()
    if "tier_calibration" in keys:
        columns.append(("Calibration", rate("tier_calibration")))
        shown_keys.add("tier_calibration")
    if "f1_lift" in keys:
        columns.append(("F1 lift", rate("f1_lift")))
        shown_keys.add("f1_lift")
    if "confirmed_warnings" in keys and "dismissed_warnings" in keys:
        columns.append(("Warnings ✓/✗", lambda row: f'{rate("confirmed_warnings")(row)} / {rate("dismissed_warnings")(row)}'))
        shown_keys.update(("confirmed_warnings", "dismissed_warnings"))
    key_note = ""
    rest = [term for term in shown["terms"] if term["key"] not in shown_keys]
    if columns:
        text = f'Calibration, F1 lift and warnings are per 100 {shown["unit"]}.'
        ranked = [row for row in shown["rows"] if row["rank"] is not None]
        rest_debits = [term for term in rest if term["group"] == "problem"]
        values = [row["per_100"].get(term["key"]) for term in rest_debits for row in ranked]
        values = [value for value in values if value is not None]
        if rest_debits and values:
            text += (
                f' Debits also cover {join_words(lower_first(t["label"]) for t in rest_debits)}, '
                f'all at most {fmt_score(max(values))} per 100 for every ranked pilot.'
            )
        key_note = text
    return role_bar_board(shown, "pilot-crews", "Pilot crews", columns=columns, key_note=key_note), shown
