"""Ranking page (split from build.py)."""

import html
import pathlib
import shutil
import sys
import analytics_page
from build_common import DATE_DIR, GAP_MODELS, ROOT, SITE, as_number, fmt_count, fmt_num, latest_analytics_dir, lower_first, page, plural
from build_notes import parse
from build_ranking_boards import ROLE_ORDER, ROLE_TITLE, SNAPSHOT_TREE, axis_pct, eligibility_rule, gate_progress, load_rank, model_detail, model_dot, money, overall_board, overall_models, overall_rule_text, percent, podium_from_index, podium_from_rank, podium_html, provider, rank_crew_line, rank_publishes_places, rank_rows, rank_withheld_reason, role_boards, settle_lag_text, stat_cards, tier_mix, whisker_axis, whisker_tick_label
from build_ranking_data import TIER_LABELS, board_window_line, crew_label, crew_name_html, fmt_score, implementer_takeaways, implementers_overall, load_scorecards, pilots_board, require_text, reviewers_group, role_rows, terms_sentence, tier_heatmap


def models_board(rank):
    """The Model rank board: scores and intervals, and bands when the board is published.

    A settled board whose scales are a window estimate, or that has not
    qualified, shows Orbit's scores and intervals with no rank numbers and
    no bands. A calibrated, qualified board is band-grouped. A live snapshot
    keeps the banded board it was published with.
    """
    e = html.escape
    publish = rank_publishes_places(rank)
    ranked, rest = rank_rows(rank)
    if not publish:
        rows = [
            row for row in rank.get("rows") or []
            if isinstance(row, dict) and isinstance(row.get("model"), str)
            and row["model"] not in GAP_MODELS and as_number(row.get("units"))
        ]
        ranked = [row for row in rows if row.get("eligible") is True and as_number(row.get("score"))]
        rest = [row for row in rows if row not in ranked]
    window = rank["window"]
    live = rank.get("live") is True
    rules = rank.get("rules") or {}
    band_pct = rules.get("band_probability")
    band_text = f"{band_pct * 100:.0f}% confidence" if as_number(band_pct) else "the board's confidence level"
    items = []
    if ranked:
        low, high, ticks = whisker_axis(ranked)
        tick_html = "".join(
            f'<span style="left:{axis_pct(tick, low, high):.2f}%">{whisker_tick_label(tick)}</span>' for tick in ticks
        )
        grid_html = "".join(
            f'<span class="{"is-ref" if tick == 100 else ""}" style="left:{axis_pct(tick, low, high):.2f}%"></span>'
            for tick in ticks
        )
        previous = None
        for row in ranked:
            if publish:
                band_start = row["rank"] != previous
                previous = row["rank"]
                label = row.get("rank_label") or str(row["rank"])
                rank_cell = (
                    f'<span class="ml-rank">{e(label) if band_start else ""}'
                    f'<span class="sr-only">{"" if band_start else "rank " + e(label)}</span></span>'
                )
                item_class = "band-start" if band_start else "band-cont"
                rank_attr = f' data-rank="{row["rank"]}"'
            else:
                # Orbit's order, with no rank number and no band.
                rank_cell = '<span class="ml-rank"><span class="sr-only">Breakdown</span></span>'
                item_class = "band-cont"
                rank_attr = ""
            interval = row.get("interval") or {}
            whisker = ""
            if as_number(interval.get("p10")) and as_number(interval.get("p90")):
                left = axis_pct(interval["p10"], low, high)
                right = axis_pct(interval["p90"], low, high)
                whisker = f'<span class="whisker prov-{provider(row["model"])}" style="left:{left:.2f}%;width:{max(right - left, 0):.2f}%"></span>'
            point = f'<span class="whisker-point prov-{provider(row["model"])}" style="left:{axis_pct(row["score"], low, high):.2f}%"></span>'
            plotted = [row["score"]] + [interval[key] for key in ("p10", "p90") if as_number(interval.get(key))]
            offscale = "".join(
                f'<span class="whisker-offscale is-{side}" title="{label} scale">{arrow}</span>'
                for side, label, arrow, clipped in (
                    ("low", "Below", "◀", min(plotted) < low),
                    ("high", "Above", "▶", max(plotted) > high),
                ) if clipped
            )
            cost = row.get("cost") or {}
            ratio = cost.get("ratio")
            ratio_html = (
                f'<span class="cost-ratio {"is-better" if ratio < 1 else "is-worse"}">{ratio:.2f}×</span>'
                if as_number(ratio) else '<span class="cost-ratio">—</span>'
            )
            crews = rank_crew_line(row)
            interval_sr = (
                f'p10 {fmt_score(interval["p10"])} to p90 {fmt_score(interval["p90"])}'
                if as_number(interval.get("p10")) and as_number(interval.get("p90")) else "no interval"
            )
            single = row.get("single_tier")
            single_html = (
                f'<span class="ml-flag">single tier{": " + e(TIER_LABELS[single].lower()) if single in TIER_LABELS else ""}</span>'
                if single else ""
            )
            items.append(
                f'<li class="{item_class}"{rank_attr}>'
                '<details class="model-row"><summary class="model-line">'
                f'{rank_cell}'
                f'<span class="ml-model">{model_dot(row["model"])}<span class="ml-name">{e(row["model"])}</span>'
                f'<span class="ml-crews">{e(crews)}</span>{single_html}</span>'
                f'<span class="ml-score">{fmt_score(row["score"])}</span>'
                f'<span class="ml-whisker"><span class="whisker-grid" aria-hidden="true">{grid_html}</span>'
                f'<span aria-hidden="true">{whisker}{point}{offscale}</span><span class="sr-only">{e(interval_sr)}</span></span>'
                f'<span class="ml-cost" data-label="$ / task"><span>{money(cost.get("per_task"))}</span>{ratio_html}</span>'
                f'<span class="ml-tasks" data-label="Tasks"><span class="ml-units">{fmt_count(row["units"])}</span>{tier_mix(row)}</span>'
                f'<span class="ml-landed" data-label="Landed">{percent(row.get("landed_rate"))}</span>'
                f'</summary>{model_detail(row, rank)}</details></li>'
            )
        head = (
            '<div class="model-line model-head" aria-hidden="true">'
            f'<span class="ml-rank">{"Rank" if publish else ""}</span>'
            '<span class="ml-model">Model</span><span class="ml-score">Score</span>'
            f'<span class="ml-whisker"><span>p10–p90 interval</span><span class="whisker-ticks">{tick_html}</span></span>'
            '<span class="ml-cost">Cost / task</span><span class="ml-tasks">Tasks · tier mix</span>'
            '<span class="ml-landed">Landed</span></div>'
        )
        board = f'<div class="model-board">{head}<ol>{"".join(items)}</ol></div>'
    else:
        need = rules.get("min_eligible_models")
        board = (
            '<p class="empty">The board has not qualified in this window'
            + (f": it needs {fmt_count(need)} models that pass the evidence gate" if as_number(need) else "")
            + ".</p>"
        )
    folded = ""
    if rest:
        rule = eligibility_rule(rank)
        rows_html = []
        for row in rest:
            fraction, reason = gate_progress(row, rules)
            rows_html.append(
                f'<li>{model_dot(row["model"])}<span class="gate-model">{e(row["model"])}</span>'
                f'<span class="gate-units">{fmt_count(row["units"])} {plural(row["units"], "task")}</span>'
                f'<span class="gate-progress"><span class="gate-track" aria-hidden="true"><span style="width:{min(fraction, 1) * 100:.0f}%"></span></span>'
                f'<span class="gate-reason">{e(reason)}</span></span></li>'
            )
        folded = (
            f'<details class="more not-ranked"><summary><span class="nr-title">Not ranked yet</span> '
            f'<span class="nr-sub">{len(rest)} {plural(len(rest), "model")}</span></summary>'
            + (f'<p class="board-note nr-rule">Orbit\'s rule: {e(rule)}</p>' if rule else "")
            + f'<ul class="gate-list">{"".join(rows_html)}</ul></details>'
        )
    if live:
        window_html = board_window_line(window["since"], window["until"], prefix="Live window")
        notice = ("This is Orbit's live model rank: provisional, because late escaped regressions "
                  "may still arrive.")
        notice_class = " is-live"
    elif publish:
        window_html = board_window_line(window["since"], window["until"], prefix="Settled window")
        notice = (
            f"The ranked 30 days end {settle_lag_text(rank)} before the snapshot, so late escaped "
            "regressions have arrived and the work is two to six weeks old."
        )
        notice_class = ""
    else:
        window_html = board_window_line(window["since"], window["until"], prefix="Settled window")
        notice = rank_withheld_reason(rank) or (
            "No ranking is published, so scores and intervals are shown without ranks or a podium."
        )
        notice_class = " is-unranked"
    if publish:
        score_key = (
            "Who implements best: Orbit's implementer rank, crews pooled into their model, eligible models only. "
            f"Shared ranks such as 2= are one band at {band_text}; cost orders a band and never crosses it. "
            "Cost ratio is the model's $ per task against the fleet's on the same tiers. Select a model for its breakdown."
        )
    else:
        score_key = (
            "Scores and p10–p90 intervals, crews pooled into their model. "
            "This board publishes no ranks and no bands. Select a model for its breakdown."
        )
    return f'''<section class="board models-board" id="models" aria-labelledby="models-title">
<div class="board-head"><h2 id="models-title">Model rank</h2>
<p class="board-key">p10–p90 whisker on a shared score axis · <span class="k-fleet" aria-hidden="true"></span> 100 is the fleet · ◀/▶ off scale</p></div>
<p class="board-note rank-notice{notice_class}">{e(notice)}</p>
<p class="board-note score-key">{e(score_key)}</p>
{window_html}
{board}
{folded}
</section>'''

def role_callouts(shown, role, board=None):
    """Callout cards for a reviewer or pilot board."""
    e = html.escape
    unit = shown["unit"]
    fleet = shown["fleet"]
    ranked = [row for row in shown["rows"] if row["rank"] is not None and row["score"] is not None]
    cards = []
    if ranked:
        top = ranked[0]
        cards.append(("Top", f'{crew_name_html(top)} {fmt_score(top["score"])}', f'{fmt_count(top["units"])} {unit} · {top["model"]}'))
        busiest = max(ranked, key=lambda row: (row["units"], -row["rank"]))
        total = sum(row["units"] for row in shown["rows"]) or 1
        cards.append((
            "Volume",
            f'{crew_name_html(busiest)} {fmt_score(busiest["score"])} on {fmt_count(busiest["units"])}',
            f'{busiest["units"] / total * 100:.0f}% of this board\'s {unit}',
        ))
        if fleet is not None:
            below = [row for row in ranked if row["score"] < fleet]
            if below:
                worst = sorted(below, key=lambda row: row["score"])[:2]
                cards.append((
                    "Below fleet",
                    ", ".join(f'{crew_name_html(row)} {fmt_score(row["score"])}' for row in worst),
                    f'{len(below)} of {len(ranked)} ranked {plural(len(ranked), "crew")} under the fleet average {fmt_score(fleet)}',
                ))
    if role == "reviewers":
        count = (board or {}).get("provisional_units")
        sub = f"{fmt_count(count)} reviews can still move" if as_number(count) and count > 0 else "scores move as findings settle"
        cards.append(("Status", "Provisional", sub))
    else:
        unranked = [row for row in shown["rows"] if row["rank"] is None]
        if unranked:
            cards.append(("Unranked", f'{len(unranked)} {plural(len(unranked), "crew")}', f'under {shown["min_support"]} {unit} or unjudged'))
    if not cards:
        return ""
    # Heads are HTML: crew names come from crew_name_html, the rest is fixed text and numbers.
    items = "".join(
        f'<li><div class="tile takeaway"><span class="tile-head">{e(label)}</span>'
        f'<span class="takeaway-head">{head}</span><span class="tile-sub">{e(sub)}</span></div></li>'
        for label, head, sub in cards
    )
    return f'<ul class="tiles takeaways" aria-label="Callouts">{items}</ul>'

def crew_role_bodies(scorecards, *, include_tiers=True):
    """Per role: (shown rows, callouts + boards HTML) for the crews-by-role section."""
    if not isinstance(scorecards, dict):
        sys.exit("scorecards.json: expected an object")
    implementers = scorecards.get("implementers")
    pilots = scorecards.get("pilots")
    reviewers = scorecards.get("reviewers")
    if not isinstance(implementers, dict) or not isinstance(pilots, dict) or not isinstance(reviewers, dict):
        sys.exit("scorecards.json: implementers, reviewers and pilots are required")
    by_tier = scorecards.get("implementers_by_tier")
    if not isinstance(by_tier, dict):
        sys.exit("scorecards.json: implementers_by_tier is required")
    impl = role_rows(implementers, "implementers")
    heatmap, slots = tier_heatmap(by_tier, impl["rows"])
    takeaways = implementer_takeaways(slots, impl["rows"], impl["terms"], require_text(by_tier, "unit", "implementers by tier"))
    reviewer_html, prov = reviewers_group(reviewers)
    pilot_html, pilot = pilots_board(pilots)
    return {
        "implementers": (impl, takeaways + implementers_overall(impl) + (heatmap if include_tiers else "")),
        "reviewers": (prov, role_callouts(prov, "reviewers", reviewers.get("provisional")) + reviewer_html),
        "pilots": (pilot, role_callouts(pilot, "pilots") + pilot_html),
    }

CREWS_NOTE = ("A crew is a model at one effort setting. Each role is scored against its own fleet rate, "
              "shown as the marker on each bar.")

def crews_by_role_html(bodies, role=None):
    """The crews-by-role component, without a role toggle of its own (ORB-23665).

    With a role it renders that role's boards under a plain "Crews" heading: the
    /ranking/ role tabs are the only role navigation. Without one it stacks every
    role under its own heading, once each, for the weekly crew-ranking note.
    """
    if role is not None:
        return f'''<section class="crews-by-role" id="crews-{role}" aria-labelledby="crews-{role}-title">
<h2 id="crews-{role}-title">Crews</h2>
<p class="board-note">{CREWS_NOTE}</p>
{bodies[role][1]}
</section>'''
    roles = "".join(
        f'''<section class="crew-role" id="crews-{key}" aria-labelledby="crews-{key}-title">
<h2 id="crews-{key}-title">{ROLE_TITLE[key]}</h2>
{bodies[key][1]}
</section>'''
        for key in ROLE_ORDER
    )
    return f'''<section class="crews-by-role" id="crews-by-role" aria-label="Crews by role">
<p class="board-note">{CREWS_NOTE}</p>
{roles}
</section>'''

def render_crews_by_role(directory, role=None):
    """Crews by role from a scorecard snapshot directory: one role, or all stacked.

    One shared component: /ranking/ renders one role in each role tab and the
    weekly crew-ranking note reuses it with every role stacked under plain
    headings, omitting the detailed tier board. The shared boards are never
    restyled per view (STD-07 §R30). Neither form draws
    a role toggle. It reads only the directory's scorecards.json.
    """
    if role is not None and role not in ROLE_ORDER:
        sys.exit(f"crews by role: unknown role {role!r}")
    return crews_by_role_html(
        crew_role_bodies(load_scorecards(directory), include_tiers=role is not None), role
    )

def weekly_ranking_notes(root=None):
    """Published weekly crew-ranking notes, newest first: (slug, date)."""
    base = (pathlib.Path(root) if root is not None else ROOT) / "notes"
    found = []
    for path in sorted(base.glob("*/index.md")):
        try:
            note = parse(path)
        except SystemExit:
            continue
        if note["status"] == "published" and note["date"] and {"rankings", "weekly"} <= set(note["tags"]):
            found.append((note["slug"], note["date"]))
    return sorted(found, key=lambda item: item[1], reverse=True)

def method_section(scorecards, rank, snapshot_date, weekly):
    e = html.escape
    boards = role_boards(scorecards)
    impl = boards["implementers"]
    cards = []
    if rank is not None:
        measures = [m for m in rank.get("measures") or [] if isinstance(m, dict)]
        total = rank.get("weights_total")
        measured = sum(m["weight"] for m in measures if m.get("status") == "measured" and as_number(m.get("weight")))
        rules = rank.get("rules") or {}
        parts = [f"{len(measures)} {plural(len(measures), 'measure')}"
                 + (f", weighted to {fmt_num(total)}; {fmt_num(measured)} are measured today." if as_number(total) else ".")]
        if as_number(rules.get("shrinkage_k")):
            parts.append(f"Scores shrink toward 100 with k = {fmt_num(rules['shrinkage_k'])}")
        if as_number(rules.get("draws")):
            parts.append(f"intervals come from {fmt_count(rules['draws'])} draws")
        if as_number(rules.get("band_probability")):
            parts.append(f"and models within {rules['band_probability'] * 100:.0f}% confidence share a band")
        text = parts[0] + (" " + ", ".join(parts[1:]) + "." if len(parts) > 1 else "")
        text += " Cost orders models inside a band and never moves one across bands. Only eligible models are ranked"
        rule = eligibility_rule(rank)
        text += f"; Orbit's rule: {lower_first(rule)}" if rule else "."
        if rank.get("live") is True:
            text += " The window is live: it ends at the snapshot, so the board is provisional while late escaped regressions may still arrive."
            text += (
                " The published board is the settled window, ending its settle lag before the snapshot,"
                " so that work is two to six weeks old."
            )
        else:
            text += (
                f" The window is settled: it ends {rank.get('settle_lag') or '14d'} before the snapshot,"
                " so the work is two to six weeks old."
            )
        text += (
            " When the scales are a window estimate, or the board has not qualified,"
            " the page shows scores and intervals without ranks or a podium and says why."
        )
        cards.append(("Model rank", text))
    else:
        cards.append(("Model rank", "This snapshot predates the model rank, so the Overall tab has no Model rank board and its podium follows the All-roles index."))
    crew_text = (
        "Per 100 units of the role's work against that role's fleet rate. "
        + (terms_sentence(impl["terms"]) + " " if impl["terms"] else "")
        + f"Crews under {impl['min_support']} units stay unranked. Reviewer scores need findings to settle, so the "
        "settled reviewer board uses its own earlier window. Orchestrators are not scored on this page."
    )
    cards.append(("Crew scorecards", crew_text))
    cards.append(("All-roles index", overall_rule_text()))
    cards.append(("What this is not", "The strongest observed contribution under the fleet's actual assignments, on Orbit's own repository. Not a verdict on a model's general capability."))
    items = "".join(f'<div class="how"><h3>{e(title)}</h3><p>{e(text)}</p></div>' for title, text in cards)
    weekly_link = (
        f'<a href="/notes/{e(weekly[0][0])}/">crew rankings in Notes</a> (latest '
        f'<time datetime="{weekly[0][1].isoformat()}">{weekly[0][1]:%b} {weekly[0][1].day}</time>'
        + (", earlier ones " + ", ".join(
            f'<a href="/notes/{e(slug)}/"><time datetime="{day.isoformat()}">{day:%b} {day.day}</time></a>'
            for slug, day in weekly[1:]
        ) if len(weekly) > 1 else "")
        + ")"
        if weekly else '<a href="/notes/">crew rankings in Notes</a>'
    )
    return f'''<section class="method-cards" id="method" aria-labelledby="method-title">
<h2 id="method-title">Method and windows</h2>
<div class="how-grid">{items}</div>
<p class="board-note method-links">Full method: <a href="/notes/crew-rankings-method/">how the crew rankings work</a>. Weekly write-ups: {weekly_link}. Data: <a href="{SNAPSHOT_TREE}{e(snapshot_date)}">snapshot JSON</a>.</p>
</section>'''

def eyebrow_window(since, until):
    """Snapshot eyebrow window: Oct 9 – Nov 8 UTC, exact stamps in datetime."""
    e = html.escape
    try:
        start, end = analytics_page.parse_time(since), analytics_page.parse_time(until)
    except ValueError:
        return f'<time datetime="{e(since)}">{e(since)}</time> – <time datetime="{e(until)}">{e(until)}</time> UTC'
    return (
        f'<time datetime="{e(since)}">{start:%b} {start.day}</time> – '
        f'<time datetime="{e(until)}">{end:%b} {end.day}</time> UTC'
    )

def render_ranking_body(scorecards, snapshot_date, rank=None, weekly=()):
    if not isinstance(snapshot_date, str) or not DATE_DIR.fullmatch(snapshot_date):
        sys.exit(f"analytics snapshot date must be YYYY-MM-DD, got {snapshot_date!r}")
    e = html.escape
    bodies = crew_role_bodies(scorecards)
    impl = bodies["implementers"][0]
    since, until = impl["window"]
    overall = overall_models(scorecards)
    rev, pil = bodies["reviewers"][0], bodies["pilots"][0]

    def ranked(shown):
        return [row for row in shown["rows"] if row["rank"] is not None]

    def units(rows):
        return sum(row["units"] for row in rows)

    index_rows = overall["rows"]
    if rank is not None:
        publish = rank_publishes_places(rank)
        model_ranked, model_rest = rank_rows(rank)
        if publish:
            leader = model_ranked[0] if model_ranked else None
            overall_stats = [
                ("Model rank", str(len(model_ranked)), f"ranked of {len(model_ranked) + len(model_rest)} models"),
                ("Top model", leader["model"] if leader else "—", fmt_score(leader["score"]) if leader else "not qualified"),
                ("All-roles index", str(len(index_rows)), "models in two or more roles"),
                ("Tasks scored", fmt_count(units(model_ranked)) or "0", "ranked models, live" if rank.get("live") is True else "ranked models"),
            ]
            podium = podium_from_rank(rank)
            podium_label = "Top three models by Model rank"
            overall_sub = f'{len(model_ranked)} {plural(len(model_ranked), "model")} · {len(index_rows)} indexed'
        else:
            scored = [
                row for row in rank.get("rows") or []
                if isinstance(row, dict) and row.get("eligible") is True and as_number(row.get("score"))
                and isinstance(row.get("model"), str) and row["model"] not in GAP_MODELS and as_number(row.get("units"))
            ]
            overall_stats = [
                ("Model rank", "—", "not published"),
                ("Top model", "—", "no ranks on this board"),
                ("All-roles index", str(len(index_rows)), "models in two or more roles"),
                ("Tasks scored", fmt_count(units(scored)) or "0", "models with a score"),
            ]
            podium = []
            podium_label = "Model rank"
            overall_sub = f'not ranked · {len(index_rows)} indexed'
        podium_note = ""
        model_html = models_board(rank)
    else:
        overall_stats = [
            ("Model rank", "—", "not in this snapshot"),
            ("All-roles index", str(len(index_rows)), "models in two or more roles"),
            ("Settled reviews", fmt_count(units(rev["rows"])) or "0", "provisional board"),
            ("Pilot assessments", fmt_count(units(pil["rows"])) or "0", f'{len(ranked(pil))} ranked {plural(len(ranked(pil)), "crew")}'),
        ]
        podium = podium_from_index(overall)
        podium_label = "Top three models by the All-roles index"
        podium_note = ('<p class="board-note podium-fallback">This snapshot has no Model rank, so the podium '
                       'follows the All-roles index.</p>' if podium else "")
        model_html = ('<p class="board-note rank-missing" id="models">Model rank: this snapshot has no rank board; '
                      'it appears with the next snapshot.</p>')
        overall_sub = f'{len(index_rows)} indexed'
    top = ranked(impl)[0] if ranked(impl) else None
    impl_stats = [
        ("Ranked crews", str(len(ranked(impl))), f'of {len(impl["rows"])}'),
        ("Implemented tasks", fmt_count(units(impl["rows"])) or "0", "30 days"),
        ("Fleet average", fmt_score(impl["fleet"]), f'per 100 {impl["unit"]}'),
        ("Top crew", crew_label(top) if top else "—", fmt_score(top["score"]) if top else ""),
    ]

    def role_stats(shown, volume, volume_sub):
        top = ranked(shown)[0] if ranked(shown) else None
        return [
            ("Ranked crews", str(len(ranked(shown))), f'of {len(shown["rows"])}'),
            (volume, fmt_count(units(shown["rows"])) or "0", volume_sub),
            ("Fleet average", fmt_score(shown["fleet"]), f'per 100 {shown["unit"]}'),
            ("Top crew", crew_label(top) if top else "—", fmt_score(top["score"]) if top else ""),
        ]

    panels = {
        "overall": (
            overall_sub,
            stat_cards(overall_stats, "Overall at a glance") + podium_html(podium, podium_label) + podium_note
            + model_html + overall_board(overall),
        ),
        "implementers": (
            f'{len(ranked(impl))} crews',
            stat_cards(impl_stats, "Implementers at a glance") + crews_by_role_html(bodies, "implementers"),
        ),
        "reviewers": (
            "provisional",
            stat_cards(role_stats(rev, "Settled reviews", "provisional board"), "Reviewers at a glance") + crews_by_role_html(bodies, "reviewers"),
        ),
        "pilots": (
            f'{len(ranked(pil))} {plural(len(ranked(pil)), "crew")}',
            stat_cards(role_stats(pil, "Assessments", "30 days"), "Pilots at a glance") + crews_by_role_html(bodies, "pilots"),
        ),
    }
    titles = {"overall": "Overall", **ROLE_TITLE}
    tabs = "".join(
        f'<li><a href="#{key}" data-tab="{key}">{titles[key]} <span class="tab-boards">{e(sub)}</span></a></li>'
        for key, (sub, _body) in panels.items()
    )
    groups = "".join(
        f'<div class="role-group" data-group="{key}" id="{key}">\n{body}\n</div>'
        for key, (_sub, body) in panels.items()
    )
    return f'''<article class="analytics ranking-page">
<p class="eyebrow">Snapshot <time datetime="{e(snapshot_date)}">{e(snapshot_date)}</time> · last 30 days · {eyebrow_window(since, until)}</p>
<h1>Ranking</h1>
<p class="summary">Which models Orbit can trust with its own work, and how each crew does in its role. Every score is against the fleet's own rate, so 100 is the expectation and higher is better.</p>
<nav class="group-nav" aria-label="Ranking views"><ul>{tabs}</ul></nav>
{groups}
{method_section(scorecards, rank, snapshot_date, list(weekly))}
</article>'''

def render_ranking_page(scorecards, snapshot_date, rank=None, weekly=None, root=None):
    if weekly is None:
        weekly = weekly_ranking_notes(root)
    return page(
        "Ranking — Constellation Works",
        "Which models Orbit can trust with its own work, and how each crew does in its role, over the last 30 days.",
        f"{SITE}/ranking/",
        render_ranking_body(scorecards, snapshot_date, rank, weekly),
        current="ranking",
        extra_css=analytics_page.ANALYTICS_CSS, extra_js=("analytics.js",),
    )

def build_ranking(root=None):
    """/ranking/ from the newest snapshot only: no archive, no picker."""
    base_root = pathlib.Path(root) if root is not None else ROOT
    directory = latest_analytics_dir(base_root)
    if directory is None:
        sys.exit("build.py: no data/analytics/<YYYY-MM-DD>/ snapshot to render")
    scorecards = load_scorecards(directory)
    rank = load_rank(directory)
    dest = base_root / "public" / "ranking"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    (dest / "index.html").write_text(
        render_ranking_page(scorecards, directory.name, rank, root=base_root), encoding="utf-8"
    )
    # The agents page moved to /ranking/; _redirects sends its old URLs there.
    stale = base_root / "public" / "analytics" / "agents"
    if stale.exists():
        shutil.rmtree(stale)
    print(f"built ranking -> {dest} from {directory.name}" + ("" if rank is not None else " (no rank.json: Models omitted)"))
