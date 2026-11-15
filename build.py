"""Build the Notes section and the public analytics pages.

Each note is a directory under notes/ holding index.md (front matter plus Markdown)
and any files the note links to (data, images). Output is a page per note, a
/notes/ index and an Atom feed. public/notes/ is generated: do not edit or commit it.

/ranking/ is rendered from the newest data/analytics/<YYYY-MM-DD>/ snapshot only (its
scorecards.json, and rank.json when the snapshot has one); it has no archive. It replaced
/analytics/agents/, whose URLs public/_redirects sends to /ranking/.
/analytics/metrics/ is rendered from the newest data/analytics/<YYYY-MM-DD>/metrics.json
via the analytics_page package. public/analytics/ and public/ranking/ are generated too: do not
edit or commit them.
/analytics/reliability/ uses the newest snapshot's reliability.json aggregates.
/analytics/experiments/ uses the newest snapshot's concluded experiments.json entries.
Each of those analytics pages also renders /analytics/<page>/<YYYY-MM>/ for every closed
calendar month from that month's last snapshot (floor 2026-11-08, no backfill),
with a no-JavaScript snapshot picker; see analytics_page.monthly_archive_entries.

Front matter is `key: value` lines between `---` fences:

    title:    required
    summary:  required; used for the index, meta description and feed
    status:   draft | published
    date:     YYYY-MM-DD, the day it was first published; required once published
    updated:  optional YYYY-MM-DD of the last material change; defaults to date
    image:    optional file in the note's directory for og:image (1200x630)
    author:   optional comma-separated authors; defaults to Constellation Works. A weekly
              crew-ranking byline, `<crew label> (<model>), MVP of the week, <score>` (the crew
              as Model rank keys it, e.g. `sol`, or `sol@high` when the key carries an effort), is one author; a weekly
              note with no MVP names its writer as `<crew> (fallback writer), no MVP this week`.
              A weekly note's title is `[Crew Ranking - <date>]: MVP <model>`, `co-MVPs <models>`
              or `no MVP`.
    tags:     optional comma-separated topics

Author, created and updated dates and tags are shown under the page title.

A weekly crew-ranking note (scripts/crew_rankings.py) carries two markers in its body:

- `<!-- crews-by-role: data/crew-rankings/<YYYY-MM-DD> -->` on its own line is replaced by
  the /ranking/ page's Crews by role component, every role stacked, rendered by the same
  render_crews_by_role from that directory's scorecards.json (STD-07 §R30);
- `{{victory-address}}` marks the writer's unwritten victory address. A draft builds with
  it; a published note that still has it fails the build.

Drafts are skipped unless --drafts is passed, so merging a draft never publishes it.
With --drafts they build marked as drafts and noindex, for local review.

Usage:  python3 build.py [--drafts]     (needs `markdown`; see README.md)
"""

import argparse
import datetime
import html
import json
import pathlib
import shutil
import sys
import analytics_page
import markdown
from build_common import ROOT, SITE, asset, HEADER, FOOTER, header_html, page, DATE_DIR, GAP_CREWS, RANK_NON_CREW, GAP_MODELS, latest_analytics_dir, gap_identity, as_number, fmt_num, fmt_count, plural, lower_first, join_words, render_window, friendly_window, _analytics_base, UTC_STAMP
from build_notes import SRC, OUT, FIELDS, MVP_BYLINE, FALLBACK_BYLINE, WEEKLY_SLUG, WEEKLY_TITLE, VICTORY_PLACEHOLDER, CREWS_EMBED, CREWS_DATA, parse, render_body, human, status, size, meta_block, rail, embed_crews_by_role, build_note, build_index, build_feed
from build_ranking_data import TIER_ORDER, TIER_LABELS, TIER_SCORE_KEY, load_scorecards, require_text, board_min_support, board_window, effort_text, crew_view, crew_key, crew_label, crew_name_html, display_rows, board_terms, fleet_average, fmt_score, tier_slots, term_extremes, per_100_rates, role_rows, bar_scale, score_bar, score_key_line, board_window_line, implementer_takeaways, weakest_term, crew_cell, rank_text, term_breakdown, implementers_overall, heat_class, tier_heatmap, role_bar_board, terms_sentence, provisional_note, thin_board_note, reviewers_group, pilots_board
from build_ranking_boards import OVERALL_RULE, ROLE_ORDER, ROLE_NOUN, ROLE_TITLE, RANK_TIERS, MODEL_PROVIDERS, SNAPSHOT_TREE, provider, model_dot, load_rank, rank_rows, pooled_models, place_models, role_boards, overall_models, overall_rule_text, stat_cards, ordinal, rank_crew_entries, rank_crew_line, podium_from_rank, podium_from_index, podium_html, role_cell, crews_text, overall_board, gate_progress, gate_fraction, eligibility_rule, money, percent, whisker_axis, whisker_tick_label, axis_pct, tier_mix, model_detail, rank_publishes_places, rank_withheld_reason, settle_lag_text
from build_ranking import models_board, role_callouts, crew_role_bodies, CREWS_NOTE, crews_by_role_html, render_crews_by_role, weekly_ranking_notes, method_section, eyebrow_window, render_ranking_body, render_ranking_page, build_ranking
from build_reliability import RELIABILITY_OUTCOMES, reliability_aggregates, reliability_table, SAFE_JOB_ID, JOB_LABELS, job_label, reliability_by_job, HOT_JOB_RATE, SPIKE_MIN_RATE, SPIKE_FACTOR, MONTH_DAY, pct, short_pct, reliability_recovery, reliability_days, day_label, daily_chart, reliability_by_job_section, clean_jobs, OUTCOME_MIX, OTHER_KEYS, render_reliability_page, _load_reliability, build_reliability
from build_experiments import EXPERIMENT_METRICS, _compact, _plain, _money_text, _money_line_text, _points_text, experiment_value, experiment_interval, _valid_interval, _diff_category, experiment_difference, experiment_difference_interval, experiment_stamp, experiment_count, experiment_metric_table, STATUS_LABEL, STOPPED_EARLY_REASON, _join_names, _lower_first, _reason_html, _finite, experiment_short_question, experiment_fidelity, _experiment_cell, _drop_unit, experiment_metric_cells, _cell_html, _cell_plot, experiment_scorecard, _status_pill, render_experiments_page, _load_experiments, build_experiments

# Re-exported so `build.<name>` keeps working for tests and scripts (see build_*.py).
__all__ = ["ROOT", "SITE", "asset", "HEADER", "FOOTER", "header_html", "page", "DATE_DIR", "GAP_CREWS", "RANK_NON_CREW", "GAP_MODELS", "latest_analytics_dir", "gap_identity", "as_number", "fmt_num", "fmt_count", "plural", "lower_first", "join_words", "render_window", "friendly_window", "_analytics_base", "UTC_STAMP", "SRC", "OUT", "FIELDS", "MVP_BYLINE", "FALLBACK_BYLINE", "WEEKLY_SLUG", "WEEKLY_TITLE", "VICTORY_PLACEHOLDER", "CREWS_EMBED", "CREWS_DATA", "parse", "render_body", "human", "status", "size", "meta_block", "rail", "embed_crews_by_role", "build_note", "build_index", "build_feed", "TIER_ORDER", "TIER_LABELS", "TIER_SCORE_KEY", "load_scorecards", "require_text", "board_min_support", "board_window", "effort_text", "crew_view", "crew_key", "crew_label", "crew_name_html", "display_rows", "board_terms", "fleet_average", "fmt_score", "tier_slots", "term_extremes", "per_100_rates", "role_rows", "bar_scale", "score_bar", "score_key_line", "board_window_line", "implementer_takeaways", "weakest_term", "crew_cell", "rank_text", "term_breakdown", "implementers_overall", "heat_class", "tier_heatmap", "role_bar_board", "terms_sentence", "provisional_note", "thin_board_note", "reviewers_group", "pilots_board", "OVERALL_RULE", "ROLE_ORDER", "ROLE_NOUN", "ROLE_TITLE", "RANK_TIERS", "MODEL_PROVIDERS", "SNAPSHOT_TREE", "provider", "model_dot", "load_rank", "rank_rows", "pooled_models", "place_models", "role_boards", "overall_models", "overall_rule_text", "stat_cards", "ordinal", "rank_crew_entries", "rank_crew_line", "podium_from_rank", "podium_from_index", "podium_html", "role_cell", "crews_text", "overall_board", "gate_progress", "gate_fraction", "eligibility_rule", "money", "percent", "whisker_axis", "whisker_tick_label", "axis_pct", "tier_mix", "model_detail", "rank_publishes_places", "rank_withheld_reason", "settle_lag_text", "models_board", "role_callouts", "crew_role_bodies", "CREWS_NOTE", "crews_by_role_html", "render_crews_by_role", "weekly_ranking_notes", "method_section", "eyebrow_window", "render_ranking_body", "render_ranking_page", "build_ranking", "RELIABILITY_OUTCOMES", "reliability_aggregates", "reliability_table", "SAFE_JOB_ID", "JOB_LABELS", "job_label", "reliability_by_job", "HOT_JOB_RATE", "SPIKE_MIN_RATE", "SPIKE_FACTOR", "MONTH_DAY", "pct", "short_pct", "reliability_recovery", "reliability_days", "day_label", "daily_chart", "reliability_by_job_section", "clean_jobs", "OUTCOME_MIX", "OTHER_KEYS", "render_reliability_page", "_load_reliability", "build_reliability", "EXPERIMENT_METRICS", "_compact", "_plain", "_money_text", "_money_line_text", "_points_text", "experiment_value", "experiment_interval", "_valid_interval", "_diff_category", "experiment_difference", "experiment_difference_interval", "experiment_stamp", "experiment_count", "experiment_metric_table", "STATUS_LABEL", "STOPPED_EARLY_REASON", "_join_names", "_lower_first", "_reason_html", "_finite", "experiment_short_question", "experiment_fidelity", "_experiment_cell", "_drop_unit", "experiment_metric_cells", "_cell_html", "_cell_plot", "experiment_scorecard", "_status_pill", "render_experiments_page", "_load_experiments", "build_experiments", "render_analytics_index", "build_analytics_index", "main"]


def render_analytics_index(directory, archives=None):
    directory = pathlib.Path(directory)
    if archives is None:
        archives = analytics_page.monthly_archive_entries(directory.parent)
    """Publish only validated window dates, never arbitrary snapshot metadata."""
    try:
        meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        window = meta["windows"]["reliability"]
        since, until = (window[key] for key in ("since", "until"))
        if window["label"] != "30d" or any(
            not isinstance(value, str) or not UTC_STAMP.fullmatch(value)
            for value in (since, until)
        ):
            raise ValueError("invalid window")
        start, end = (datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
                      for value in (since, until))
        if end - start != datetime.timedelta(days=30):
            raise ValueError("invalid window duration")
        if not DATE_DIR.fullmatch(directory.name):
            raise ValueError("invalid snapshot date")
        datetime.date.fromisoformat(directory.name)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        sys.exit("build.py: newest snapshot must contain a valid 30-day reliability window in meta.json")

    cards = (
        ("metrics", "Metrics", "Task outcomes, duration, cost and other delivery measures."),
        ("reliability", "Reliability", "Run outcomes and failure rates across the fleet."),
        ("experiments", "Experiments", "Results and observations from concluded experiments."),
    )
    items = "\n".join(
        ['<li><div><h2><a href="/ranking/">Ranking</a></h2>'
         '<p>Model rank and crew scorecards for implementers, reviewers and pilots, last 30 days.</p></div></li>']
        + [
            f'<li><div><h2><a href="/analytics/{slug}/">{title}</a></h2>'
            f'<p>{description}</p></div></li>'
            for slug, title, description in cards
        ]
    )
    e = html.escape
    if archives:
        month_items = "\n".join(
            f'<li><time datetime="{e(entry["month"])}">{e(analytics_page.month_label(entry["month"]))}</time> '
            f'(<time datetime="{e(entry["month"])}">{e(entry["month"])}</time>), snapshot '
            f'<time datetime="{e(entry["date"])}">{e(entry["date"])}</time>'
            + (f', window <time datetime="{e(entry["since"])}">{e(entry["since"][:10])}</time> to '
               f'<time datetime="{e(entry["until"])}">{e(entry["until"][:10])}</time>' if entry.get("since") and entry.get("until") else "")
            + ": "
            + ", ".join(f'<a href="/analytics/{slug}/{e(entry["month"])}/">{title}</a>' for slug, title, _desc in cards)
            + "</li>"
            for entry in archives
        )
        months_html = (
            '<section class="snapshot-months"><h2>Available months</h2>'
            '<p>Latest is the newest snapshot; each archived month below is that '
            "month's last snapshot.</p>"
            f'<ul>{month_items}</ul></section>'
        )
    else:
        months_html = (
            '<section class="snapshot-months"><h2>Available months</h2>'
            "<p>No archived months yet: only the latest snapshot is available. "
            'The first archived month will be <time datetime="2026-11">2026-11</time>, '
            "once November's month-end snapshot exists and a later snapshot follows it.</p></section>"
        )
    body = f'''<article class="index analytics-index">
<h1>Analytics</h1>
<p class="summary">Public snapshots of how Orbit crews and workflows perform.</p>
<p>Snapshot <time datetime="{directory.name}">{directory.name}</time>. Reference 30-day UTC window: <time datetime="{since}">{start.date().isoformat()}</time> to <time datetime="{until}">{end.date().isoformat()}</time>. Individual boards may use different windows; experiments use cumulative observation periods.</p>
<p>Read <a href="/notes/crew-rankings-method/">how the crew rankings work</a>.</p>
<ul class="notes">{items}</ul>
{months_html}
</article>'''
    return page("Analytics | Constellation Works", "Public analytics for Orbit crews and workflows.",
                f"{SITE}/analytics/", body, current="analytics")

def build_analytics_index(root=None):
    base_root = pathlib.Path(root) if root is not None else ROOT
    directory = latest_analytics_dir(base_root)
    if directory is None:
        sys.exit("build.py: no analytics snapshot to render")
    dest = base_root / "public" / "analytics"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "index.html").write_text(render_analytics_index(directory), encoding="utf-8")
    print(f"built analytics index -> {dest} from {directory.name}")

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--drafts", action="store_true", help="include drafts, marked and noindex")
    args = ap.parse_args()

    notes = [parse(p) for p in sorted(SRC.glob("*/index.md"))]
    shown = [n for n in notes if n["status"] == "published" or args.drafts]
    # Newest first; undated drafts sort above everything.
    shown.sort(key=lambda n: n["date"] or datetime.date.max, reverse=True)

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for n in shown:
        build_note(n)
    build_index(shown)
    build_feed(shown)
    skipped = len(notes) - len(shown)
    print(f"built {len(shown)} note(s) -> {OUT}" + (f"; skipped {skipped} draft(s)" if skipped else ""))
    build_analytics_index()
    build_ranking()
    analytics_page.build(ROOT)
    build_reliability()
    build_experiments()

if __name__ == "__main__":
    main()
