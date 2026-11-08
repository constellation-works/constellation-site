#!/usr/bin/env python3
"""Build the Notes section and the public analytics pages.

Each note is a directory under notes/ holding index.md (front matter plus Markdown)
and any files the note links to (data, images). Output is a page per note, a
/notes/ index and an Atom feed. public/notes/ is generated: do not edit or commit it.

/analytics/agents/ is rendered from the newest data/analytics/<YYYY-MM-DD>/scorecards.json.
/analytics/metrics/ is rendered from the newest data/analytics/<YYYY-MM-DD>/metrics.json
via analytics_page.py. public/analytics/ is generated too: do not edit or commit it.
/analytics/reliability/ uses the newest snapshot's reliability.json aggregates.
/analytics/experiments/ uses the newest snapshot's concluded experiments.json entries.
Each analytics page also renders /analytics/<page>/<YYYY-MM>/ for every closed
calendar month from that month's last snapshot (floor 2026-11-08, no backfill),
with a no-JavaScript snapshot picker; see analytics_page.monthly_archive_entries.

Front matter is `key: value` lines between `---` fences:

    title:    required
    summary:  required; used for the index, meta description and feed
    status:   draft | published
    date:     YYYY-MM-DD, the day it was first published; required once published
    updated:  optional YYYY-MM-DD of the last material change; defaults to date
    image:    optional file in the note's directory for og:image (1200x630)
    author:   optional comma-separated authors; defaults to Constellation Works
    tags:     optional comma-separated topics

Author, created and updated dates and tags are shown under the page title.

Drafts are skipped unless --drafts is passed, so merging a draft never publishes it.
With --drafts they build marked as drafts and noindex, for local review.

Usage:  python3 build.py [--drafts]     (needs `markdown`; see README.md)
"""

import argparse
import datetime
import hashlib
import html
import json
import math
import pathlib
import re
import shutil
import sys

import analytics_page
import markdown

ROOT = pathlib.Path(__file__).parent
SRC = ROOT / "notes"
OUT = ROOT / "public" / "notes"
SITE = "https://constellation-works.com"

FIELDS = {"title", "summary", "status", "date", "updated", "image", "author", "tags"}


def asset(name):
    """URL of a file in public/assets/ with a content hash, so a changed file is
    fetched again instead of served from a browser cache (the host caches for hours)."""
    digest = hashlib.sha256((ROOT / "public" / "assets" / name).read_bytes()).hexdigest()
    return f"/assets/{name}?v={digest[:10]}"


def parse(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        sys.exit(f"{path}: missing front matter")
    meta = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        key = key.strip()
        if not sep or key not in FIELDS:
            sys.exit(f"{path}: bad front matter line: {line!r}")
        meta[key] = value.strip()
    for key in ("title", "summary", "status"):
        if not meta.get(key):
            sys.exit(f"{path}: {key} is required")
    if meta["status"] not in ("draft", "published"):
        sys.exit(f"{path}: status must be draft or published")
    if meta.get("date"):
        meta["date"] = datetime.date.fromisoformat(meta["date"])
    elif meta["status"] == "published":
        sys.exit(f"{path}: a published note needs a date")
    else:
        meta["date"] = None
    meta["updated"] = datetime.date.fromisoformat(meta["updated"]) if meta.get("updated") else meta["date"]
    if meta["updated"] and meta["date"] and meta["updated"] < meta["date"]:
        sys.exit(f"{path}: updated is before date")
    meta["tags"] = [t.strip() for t in meta.get("tags", "").split(",") if t.strip()]
    meta["authors"] = [a.strip() for a in meta.get("author", "").split(",") if a.strip()] or ["Constellation Works"]
    if meta.get("image") and not (path.parent / meta["image"]).is_file():
        sys.exit(f"{path}: image {meta['image']} not found")
    meta["slug"] = path.parent.name
    meta["body"] = text[m.end():]
    return meta


def render_body(md):
    out = markdown.markdown(
        md, extensions=["tables", "fenced_code", "toc"], output_format="html"
    )
    # Tables scroll inside their own box so a wide one never scrolls the page.
    out = out.replace("<table>", '<div class="table"><table>').replace(
        "</table>", "</table></div>"
    )
    # A quote's attribution is the paragraph that starts with an em dash.
    return out.replace("<p>\u2014 ", '<p class="by">\u2014 ')


def human(d):
    return f"{d:%B} {d.day}, {d.year}" if d else "Unpublished draft"


HEADER = """<header>
  <div class="wrap bar">
    <a class="brand" href="/">
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <mask id="hm" maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100">
          <rect width="100" height="100" fill="#fff"/>
          <circle cx="23.87" cy="47.41" r="7.6" fill="#000"/>
          <circle cx="74.62" cy="63.52" r="8" fill="#000"/>
        </mask>
        <g mask="url(#hm)" fill="none" stroke="currentColor" stroke-width="3.4">
          <ellipse cx="50" cy="50" rx="34" ry="19" transform="rotate(-28 50 50)"/>
          <ellipse cx="50" cy="50" rx="45" ry="25" transform="rotate(-28 50 50)"/>
        </g>
        <g fill="currentColor">
          <circle cx="23.87" cy="47.41" r="5.2"/>
          <circle cx="74.62" cy="63.52" r="5.6"/>
        </g>
      </svg>
      <b>constellation<span> works</span></b>
    </a>
    <nav>
      <a href="/notes/" aria-current="page">Notes</a>
      <a href="/analytics/">Analytics</a>
      <a class="nav-orbit" href="https://orbit-cli.com">Orbit</a>
      <a href="https://github.com/constellation-works">GitHub</a>
      <button class="theme" type="button" aria-label="Switch to light theme" hidden>
        <svg class="sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>
        <svg class="moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>
      </button>
    </nav>
  </div>
</header>"""

FOOTER = f"""<footer>
  <div class="wrap">
    <span>&copy; 2026 Constellation Works</span>
    <span class="sp">
      <a href="/notes/feed.xml">Atom feed</a>
      <a href="https://github.com/constellation-works">github.com/constellation-works</a>
    </span>
  </div>
</footer>
<script src="{asset('theme.js')}"></script>"""


def header_html(current="notes"):
    """Mark the active section in the shared navigation."""
    if current == "notes":
        return HEADER
    header = HEADER.replace(' aria-current="page"', "", 1)
    if current == "analytics":
        header = header.replace('href="/analytics/"', 'href="/analytics/" aria-current="page"', 1)
    return header


def page(title, description, url, body, image=None, draft=False, kind="website", current="notes"):
    e = html.escape
    img = image or f"{SITE}/brand/png/cw-lockup-light-1520.png"
    robots = '<meta name="robots" content="noindex">\n' if draft else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
{robots}<link rel="canonical" href="{e(url)}">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/brand/png/cw-favicon-180.png">
<link rel="alternate" type="application/atom+xml" title="Constellation Works notes" href="/notes/feed.xml">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:type" content="{kind}">
<meta property="og:url" content="{e(url)}">
<meta property="og:image" content="{e(img)}">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="{asset('notes.css')}">
<script src="{asset('theme-init.js')}"></script>
</head>
<body>
{header_html(current)}
<main class="wrap">
{body}
</main>
{FOOTER}
</body>
</html>
"""


def status(note):
    if note["status"] != "draft":
        return ""
    return '<p class="status">Draft, not published</p>\n'


def size(path):
    n = path.stat().st_size
    return f"{n} B" if n < 1024 else f"{round(n / 1024)} KB"


def meta_block(note):
    """Under the title: author, created and updated dates, tags."""
    e = html.escape

    def when(d):
        return f'<time datetime="{d.isoformat()}">{human(d)}</time>' if d else "Not published"

    names = [e(a) for a in note["authors"]]
    byline = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    rows = [("Author" if len(names) == 1 else "Authors", byline), ("Created", when(note["date"])),
            ("Updated", when(note["updated"]))]
    if note["tags"]:
        rows.append(("Tags", "".join(f'<span class="tag">{e(t)}</span>' for t in note["tags"])))
    items = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in rows)
    return f'<dl class="meta">{items}</dl>'


def rail(note, files):
    """Margin column: draft status, then the files the note publishes."""
    items = "".join(
        f'<li><a href="{html.escape(f.name)}">{html.escape(f.name)}</a> {size(f)}</li>\n'
        for f in files
    )
    listing = f'<ul class="files">\n<li>Data</li>\n{items}</ul>\n' if files else ""
    return f'<aside class="rail">\n{status(note)}{listing}</aside>'


def build_note(note):
    e = html.escape
    url = f"{SITE}/notes/{note['slug']}/"
    image = f"{url}{note['image']}" if note.get("image") else None
    src = SRC / note["slug"]
    # Everything beside index.md is published; the link card is not listed as data.
    files = sorted(f for f in src.iterdir() if f.is_file() and f.name != "index.md")
    data = [f for f in files if f.name != note.get("image")]
    # The rail comes last so narrow screens list the data after the text; wide screens
    # still place it in the margin beside the title (grid-row in notes.css).
    body = f"""<article class="note">
<h1>{e(note['title'])}</h1>
{meta_block(note)}
<p class="summary">{e(note['summary'])}</p>
{render_body(note['body'])}
{rail(note, data)}
</article>"""
    dest = OUT / note["slug"]
    dest.mkdir(parents=True)
    for f in files:
        shutil.copy2(f, dest / f.name)
    title = f"{note['title']} — Constellation Works"
    (dest / "index.html").write_text(
        page(title, note["summary"], url, body, image, note["status"] == "draft", "article"),
        encoding="utf-8",
    )


def build_index(notes):
    e = html.escape
    items = "".join(
        f"""<li>
  <div class="when"><p>{human(n['date']) if n['date'] else ''}</p>{status(n)}</div>
  <div><h2><a href="/notes/{n['slug']}/">{e(n['title'])}</a></h2>
  <p>{e(n['summary'])}</p></div>
</li>
"""
        for n in notes
    ) or '<li><div></div><p>No notes are published yet.</p></li>\n'
    body = f"""<section class="index">
<h1>Notes</h1>
<p class="summary">Research and operating data from building and running Orbit, a
local-first runtime for coding agents. Each note publishes the data behind it.</p>
<ul class="notes">
{items}</ul>
</section>"""
    (OUT / "index.html").write_text(
        page(
            "Notes — Constellation Works",
            "Research and operating data from building and running Orbit.",
            f"{SITE}/notes/",
            body,
            draft=any(n["status"] == "draft" for n in notes),
        ),
        encoding="utf-8",
    )


def build_feed(notes):
    e = html.escape
    dated = [n for n in notes if n["date"]]
    updated = max((n["updated"] for n in dated), default=datetime.date(2026, 1, 1))
    entries = "".join(
        f"""  <entry>
    <title>{e(n['title'])}</title>
    <link href="{SITE}/notes/{n['slug']}/"/>
    <id>{SITE}/notes/{n['slug']}/</id>
    <published>{n['date'].isoformat()}T00:00:00Z</published>
    <updated>{n['updated'].isoformat()}T00:00:00Z</updated>
    <summary>{e(n['summary'])}</summary>
{''.join(f'    <author><name>{e(a)}</name></author>' + chr(10) for a in n['authors'])}{''.join(f'    <category term="{e(t)}"/>' + chr(10) for t in n['tags'])}  </entry>
"""
        for n in dated
    )
    (OUT / "feed.xml").write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Constellation Works notes</title>
  <link href="{SITE}/notes/"/>
  <link rel="self" href="{SITE}/notes/feed.xml"/>
  <id>{SITE}/notes/</id>
  <updated>{updated.isoformat()}T00:00:00Z</updated>
  <author><name>Constellation Works</name></author>
{entries}</feed>
""",
        encoding="utf-8",
    )


DATE_DIR = re.compile(r"\d{4}-\d{2}-\d{2}")
# Same attribution gaps analytics_snapshot.py drops before a row is public.
GAP_CREWS = {"crew unknown", "crew unavailable", "unknown"}
GAP_MODELS = {"model unknown"}
TIER_ORDER = ("low", "medium", "hard", "xhard")
TIER_LABELS = {"low": "Low", "medium": "Medium", "hard": "Hard", "xhard": "Extra hard"}
# The dashboard's tier control: one score per crew and model, not per task type.
TIER_SCORE_KEY = (
    "Score: tier crew score per 100 tasks, support summed across task types, "
    "against the fleet's rates on this tier; 100 is the fleet average."
)


def latest_analytics_dir(root=None):
    """Newest data/analytics/<YYYY-MM-DD>/ that the site can render."""
    base = (pathlib.Path(root) if root is not None else ROOT) / "data" / "analytics"
    if not base.is_dir():
        return None
    dated = [path for path in base.iterdir() if path.is_dir() and DATE_DIR.fullmatch(path.name)]
    if not dated:
        return None
    newest = max(dated, key=lambda path: path.name)
    if not (newest / "scorecards.json").is_file():
        sys.exit(f"{newest}: newest analytics snapshot has no scorecards.json")
    return newest


def load_scorecards(directory):
    path = pathlib.Path(directory) / "scorecards.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"{path}: invalid JSON ({exc})")
    if not isinstance(data, dict):
        sys.exit(f"{path}: expected an object")
    return data


def gap_identity(crew, model):
    return crew in GAP_CREWS or model in GAP_MODELS


def as_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def fmt_num(value):
    if not as_number(value):
        return None
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def fmt_count(value):
    text = fmt_num(value)
    if text is None:
        return None
    if text.isdigit():
        return f"{int(text):,}"
    return text


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
        ),
    )
    return {
        "unit": unit,
        "min_support": min_support,
        "rows": ranked + rest,
        "window": board_window(board, name),
        "score_key": require_text(board, "score_key", name),
    }


def role_board(board, name, title, element_id, label=None, note=None, nav=None):
    shown = display_rows(board, name)
    shown.update({
        "id": element_id,
        "title": title,
        "label": label,
        "note": note,
        "nav": nav or title,
    })
    return shown


def provisional_note(board):
    count = board.get("provisional_units")
    if not as_number(count) or count <= 0:
        return None
    return f"{fmt_count(count)} reviews in this window are still provisional."


def tier_rows(block):
    """One board per complexity tier, ranked as the dashboard's tier control ranks.

    Support is the sum of that crew's task-type cells. The score is the tier
    crew score (``crew_mean``), and a row under ``min_support`` stays unranked.
    """
    name = "implementers by tier"
    unit = require_text(block, "unit", name)
    min_support = board_min_support(block, name)
    window = board_window(block, name)
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
        slot = grouped[tier].setdefault(
            (crew, model), {"crew": crew, "model": model, "units": 0.0, "score": None}
        )
        slot["units"] += count
        if slot["score"] is None and as_number(cell.get("crew_mean")):
            slot["score"] = cell["crew_mean"]
    boards = []
    for tier in TIER_ORDER:
        prepared = []
        for slot in grouped[tier].values():
            if slot["score"] is None:
                continue
            prepared.append({
                "crew": slot["crew"],
                "model": slot["model"],
                "units": slot["units"],
                "score": slot["score"],
                "rank": None,
                "below": slot["units"] < min_support,
            })
        ranked = sorted(
            (row for row in prepared if not row["below"]),
            key=lambda row: (-row["score"], -row["units"], row["crew"], row["model"]),
        )
        for index, row in enumerate(ranked, 1):
            row["rank"] = index
        rest = sorted(
            (row for row in prepared if row["below"]),
            key=lambda row: (-row["score"], -row["units"], row["crew"], row["model"]),
        )
        rows = ranked + rest
        if not rows:
            continue
        label = TIER_LABELS[tier]
        boards.append({
            "id": f"implementers-{tier}",
            "title": f"Implementers, {label.lower()} tier",
            "nav": f"{label} tier",
            "label": None,
            "note": None,
            "unit": unit,
            "min_support": min_support,
            "rows": rows,
            "window": window,
            "score_key": TIER_SCORE_KEY,
        })
    return boards


def agents_boards(scorecards):
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
    settled = reviewers.get("settled")
    if settled is not None and not isinstance(settled, dict):
        sys.exit("scorecards.json: reviewers.settled is not a board")
    by_tier = scorecards.get("implementers_by_tier")
    if not isinstance(by_tier, dict):
        sys.exit("scorecards.json: implementers_by_tier is required")
    boards = [role_board(implementers, "implementers", "Implementers", "implementers", nav="Implementers")]
    boards.extend(tier_rows(by_tier))
    boards.append(role_board(
        provisional, "reviewers provisional", "Reviewers", "reviewers",
        label="Provisional", note=provisional_note(provisional), nav="Reviewers",
    ))
    if isinstance(settled, dict):
        boards.append(role_board(
            settled, "reviewers settled", "Reviewers", "reviewers-settled",
            label="Settled", nav="Reviewers, settled",
        ))
    boards.append(role_board(pilots, "pilots", "Pilots", "pilots", nav="Pilots"))
    return boards


def render_window(since, until):
    e = html.escape
    return (
        f'<p class="board-window">Window <time datetime="{e(since)}">{e(since)}</time>'
        f' to <time datetime="{e(until)}">{e(until)}</time> UTC.</p>'
    )


def render_table(board):
    e = html.escape
    unit = board["unit"]
    if not board["rows"]:
        body = '<p class="empty">No rows in this window.</p>'
    else:
        rows = []
        for row in board["rows"]:
            if row["rank"] is None:
                rank_html = '<td data-label="Rank" class="rank unranked"><span class="value">unranked</span></td>'
                rank_attr = "unranked"
            else:
                rank_html = f'<td data-label="Rank" class="rank"><span class="value">{row["rank"]}</span></td>'
                rank_attr = str(row["rank"])
            score = fmt_num(row["score"])
            score_text = e(score) if score is not None else "unjudged"
            units = e(fmt_num(row["units"]))
            rows.append(
                f'<tr data-rank="{rank_attr}">'
                f"{rank_html}"
                f'<td data-label="Crew"><span class="value">{e(row["crew"])}</span></td>'
                f'<td data-label="Model"><span class="value">{e(row["model"])}</span></td>'
                f'<td data-label="Score" class="num"><span class="value"><span class="num">{score_text}</span> '
                f'<span class="unit">per 100 {e(unit)}</span></span></td>'
                f'<td data-label="Units" class="num"><span class="value"><span class="num">{units}</span> '
                f'<span class="unit">{e(unit)}</span></span></td>'
                f"</tr>"
            )
        def render_rows(part, overflow):
            caption = (
                f'<caption class="sr-only">Additional entries for {e(board["title"])}</caption>'
                if overflow else f'<caption class="sr-only">{e(board["title"])}</caption>'
            )
            return f'''<div class="table">
<table>
{caption}
<thead><tr>
<th class="rank">Rank</th><th>Crew</th><th>Model</th><th class="num">Score</th><th class="num">Units</th>
</tr></thead>
<tbody>
{"".join(part)}
</tbody>
</table>
</div>'''
        body = analytics_page.with_row_disclosure(rows, render_rows, "entries")
    return (
        f"{body}\n"
        f'<p class="support-note">Rows under {board["min_support"]} {e(unit)} stay unranked.</p>'
    )


def render_board(board):
    e = html.escape
    label = f' <span class="board-label">{e(board["label"])}</span>' if board.get("label") else ""
    note = f'<p class="board-note">{e(board["note"])}</p>\n' if board.get("note") else ""
    since, until = board["window"]
    return f'''<section class="board" id="{e(board["id"])}">
<h2>{e(board["title"])}{label}</h2>
{render_window(since, until)}
<p class="score-key">{e(board["score_key"])}</p>
{note}{render_table(board)}
</section>'''


def _analytics_base(root=None):
    return (pathlib.Path(root) if root is not None else ROOT) / "data" / "analytics"


def render_agents_body(scorecards, snapshot_date, picker="", banner=""):
    if not isinstance(snapshot_date, str) or not DATE_DIR.fullmatch(snapshot_date):
        sys.exit(f"analytics snapshot date must be YYYY-MM-DD, got {snapshot_date!r}")
    boards = agents_boards(scorecards)
    e = html.escape
    nav = "\n".join(f'<a href="#{e(board["id"])}">{e(board["nav"])}</a>' for board in boards)
    sections = "\n".join(render_board(board) for board in boards)
    return f'''<article class="analytics">
<h1>Agent scorecards</h1>
{banner}{picker}
<p class="summary">Implementer, reviewer and pilot crews from the daily public snapshot. Each scorecard shows its own window. How a score is built is <a href="/notes/crew-rankings-method/">how the crew rankings work</a>.</p>
<p class="as-of">Snapshot {e(snapshot_date)}.</p>
<nav class="board-nav" aria-label="Scorecards">
{nav}
</nav>
{sections}
</article>'''


def render_agents_page(scorecards, snapshot_date, picker=None, banner="", archive_month=None, url=None, root=None):
    if picker is None:
        picker = analytics_page.picker_html(_analytics_base(root), "agents", "scorecards.json", archive_month)
    return page(
        "Agent scorecards — Constellation Works",
        "Implementer, reviewer and pilot scorecards from the daily public snapshot, each with its own window.",
        url or f"{SITE}/analytics/agents/",
        render_agents_body(scorecards, snapshot_date, picker, banner),
        current="analytics",
    )


def build_agents(root=None):
    base_root = pathlib.Path(root) if root is not None else ROOT
    directory = latest_analytics_dir(base_root)
    if directory is None:
        sys.exit("build.py: no data/analytics/<YYYY-MM-DD>/ snapshot to render")
    scorecards = load_scorecards(directory)
    dest = base_root / "public" / "analytics" / "agents"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    (dest / "index.html").write_text(
        render_agents_page(scorecards, directory.name, root=base_root), encoding="utf-8"
    )
    print(f"built agent scorecards -> {dest} from {directory.name}")
    for entry in analytics_page.monthly_archive_entries(_analytics_base(base_root), "scorecards.json", "agents"):
        month_dest = dest / entry["month"]
        month_dest.mkdir(parents=True)
        (month_dest / "index.html").write_text(
            render_agents_page(
                load_scorecards(entry["directory"]), entry["date"],
                picker=analytics_page.picker_html(_analytics_base(base_root), "agents", "scorecards.json", entry["month"]),
                banner=analytics_page.archive_banner("agents", entry),
                archive_month=entry["month"],
                url=f"{SITE}/analytics/agents/{entry['month']}/",
                root=base_root,
            ),
            encoding="utf-8",
        )
        print(f"built agent scorecards archive {entry['month']} -> {month_dest} from {entry['date']}")


RELIABILITY_OUTCOMES = (
    ("succeeded", "Succeeded"),
    ("failed", "Direct failures"),
    ("cascaded", "Cascaded failures"),
    ("cancelled", "Cancelled"),
    ("held", "Held"),
    ("upgrade_paused", "Paused for upgrade"),
    ("in_flight", "In flight"),
    ("skipped", "Skipped"),
    ("unknown", "Unknown outcome"),
)
UTC_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z")


def reliability_aggregates(data):
    """Project only known numeric fields and validated timestamps, never labels.

    In particular, source, by_job, activities, observed_states and arbitrary
    future diagnostic fields have no route into the public HTML.
    """
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        sys.exit("reliability.json: expected schema_version 1")
    window = data.get("window")
    if not isinstance(window, dict) or window.get("label") != "30d":
        sys.exit("reliability.json: expected a 30d UTC window")
    stamps = [window.get(key) for key in ("since", "until")]
    if any(not isinstance(value, str) or not UTC_STAMP.fullmatch(value) for value in stamps):
        sys.exit("reliability.json: expected exact UTC since/until timestamps")
    try:
        since, until = [datetime.datetime.fromisoformat(value.replace("Z", "+00:00")) for value in stamps]
    except ValueError:
        sys.exit("reliability.json: invalid UTC timestamp")
    if until - since != datetime.timedelta(days=30):
        sys.exit("reliability.json: UTC window must span 30 days")
    totals = data.get("totals")
    runs = totals.get("job_runs") if isinstance(totals, dict) else None
    counts = runs.get("counts") if isinstance(runs, dict) else None
    keys = ("total",) + tuple(key for key, _label in RELIABILITY_OUTCOMES)
    if not isinstance(counts, dict) or any(type(counts.get(key)) is not int or counts[key] < 0 for key in keys):
        sys.exit("reliability.json: expected non-negative integer outcome counts")
    if counts["total"] != sum(counts[key] for key, _label in RELIABILITY_OUTCOMES):
        sys.exit("reliability.json: outcome counts do not add up to total")
    return {key: counts[key] for key in keys}, stamps


def reliability_table(rows, denominator, caption):
    """Rates are recomputed from counts; zero support never becomes 0% success."""
    rendered = []
    for label, count in rows:
        rate = f"{count / denominator:.2%}" if denominator else "Unavailable"
        rendered.append(
            f'<tr><td data-label="Outcome"><span class="value">{html.escape(label)}</span></td>'
            f'<td class="num" data-label="Count"><span class="value">{count:,} runs</span></td>'
            f'<td class="num" data-label="Rate"><span class="value">{rate}</span></td></tr>'
        )
    return (
        '<div class="table"><table>'
        f'<caption class="sr-only">{html.escape(caption)}</caption>'
        '<thead><tr><th scope="col">Outcome</th><th scope="col" class="num">Count (runs)</th>'
        '<th scope="col" class="num">Rate (%)</th></tr></thead>'
        f'<tbody>{"".join(rendered)}</tbody></table></div>'
    )


def render_reliability_page(data, snapshot_date, picker=None, banner="", archive_month=None, url=None, root=None):
    if picker is None:
        picker = analytics_page.picker_html(_analytics_base(root), "reliability", "reliability.json", archive_month)
    if not isinstance(snapshot_date, str) or not DATE_DIR.fullmatch(snapshot_date):
        sys.exit("reliability snapshot date must be YYYY-MM-DD")
    counts, (since, until) = reliability_aggregates(data)
    settled = counts["succeeded"] + counts["failed"]
    window = render_window(since, until)
    outcomes = dict(RELIABILITY_OUTCOMES)
    sections = []
    boards = (
        ("settled", "Success and failure", ("succeeded", "failed"), settled,
         "Rates use successes plus direct failures. Cascaded failures are wrapper echoes "
         "rolled into the originating failure, so they are excluded from this denominator."),
        ("failures", "Failure categories", ("failed", "cascaded"), counts["total"],
         "Direct failures and cascaded failures are shown separately. Each rate is a share "
         "of all recorded runs, including unsettled and other outcomes."),
        ("other-outcomes", "Other outcomes",
         ("cancelled", "held", "upgrade_paused", "in_flight", "skipped", "unknown"), counts["total"],
         "These outcomes are excluded from the success and failure rates above. "
         "Each rate here is a share of all recorded runs."),
    )
    for element_id, title, keys, denominator, note in boards:
        rows = [(outcomes[key], counts[key]) for key in keys]
        sections.append(
            f'<section class="board" id="{element_id}"><h2>{title}</h2>{window}'
            f'<p class="score-key">{note}</p>'
            f'<p class="board-note">Denominator: {denominator:,} runs.</p>'
            + reliability_table(rows, denominator, title) + '</section>'
        )
    empty = '<p class="empty">No recorded runs in this window. Rates are unavailable.</p>' if not counts["total"] else ""
    body = f'''<article class="analytics">
<h1>Reliability</h1>
{banner}{picker}
<p class="summary">Success, failure and other outcomes across the fleet over 30 days, from the daily public snapshot.</p>
<p class="as-of">Snapshot {snapshot_date}. {counts["total"]:,} recorded runs; {settled:,} settled outcomes.</p>
<nav class="board-nav" aria-label="Reliability">
<a href="#settled">Success and failure</a><a href="#failures">Failure categories</a><a href="#other-outcomes">Other outcomes</a>
</nav>
{empty}{"".join(sections)}
<p class="board-note">Counts reflect the snapshot at collection time; in-flight and held outcomes can change in later snapshots. Rates describe observed outcomes, not a causal comparison of crews.</p>
</article>'''
    return page(
        "Reliability — Constellation Works",
        "Aggregate Orbit success and failure counts and rates over 30 days.",
        url or f"{SITE}/analytics/reliability/", body, current="analytics",
    )


def _load_reliability(directory):
    try:
        return json.loads((pathlib.Path(directory) / "reliability.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        sys.exit("build.py: newest snapshot must contain valid reliability.json")


def build_reliability(root=None):
    base_root = pathlib.Path(root) if root is not None else ROOT
    directory = latest_analytics_dir(base_root)
    if directory is None:
        sys.exit("build.py: no data/analytics/<YYYY-MM-DD>/ snapshot to render")
    data = _load_reliability(directory)
    rendered = render_reliability_page(data, directory.name, root=base_root)
    dest = base_root / "public" / "analytics" / "reliability"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    (dest / "index.html").write_text(rendered, encoding="utf-8")
    print(f"built reliability -> {dest} from {directory.name}")
    for entry in analytics_page.monthly_archive_entries(_analytics_base(base_root), "reliability.json", "reliability"):
        month_dest = dest / entry["month"]
        month_dest.mkdir(parents=True)
        (month_dest / "index.html").write_text(
            render_reliability_page(
                _load_reliability(entry["directory"]), entry["date"],
                picker=analytics_page.picker_html(_analytics_base(base_root), "reliability", "reliability.json", entry["month"]),
                banner=analytics_page.archive_banner("reliability", entry),
                archive_month=entry["month"],
                url=f"{SITE}/analytics/reliability/{entry['month']}/",
                root=base_root,
            ),
            encoding="utf-8",
        )
        print(f"built reliability archive {entry['month']} -> {month_dest} from {entry['date']}")


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


def experiment_value(value, unit):
    if not as_number(value) or not math.isfinite(value):
        return "Unavailable"
    if unit == "%":
        return f"{value:.1%}"
    if unit == "USD":
        return f"${value:,.2f}"
    if unit == "USD/line":
        return f"${value:,.4f} / line"
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
        return f"{sign}{a * 100:.1f} points"
    if category == "money":
        return f"{sign}${a:,.2f}"
    if category == "money_line":
        return f"{sign}${a:,.4f} / line"
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


def _diff_verdict(estimate, better):
    if estimate == 0:
        return "same", "same as control"
    if better == "higher":
        return ("better", "better than control") if estimate > 0 else ("worse", "worse than control")
    if better == "lower":
        return ("better", "better than control") if estimate < 0 else ("worse", "worse than control")
    return ("higher", "higher than control") if estimate > 0 else ("lower", "lower than control")


def experiment_diff_metric(metric, arms, kind_label):
    """One static chart group for a metric, from its projected differences only."""
    e = html.escape
    key = metric.get("metric")
    label, _ = EXPERIMENT_METRICS[key]
    better = metric.get("better") if metric.get("better") in ("higher", "lower") else None
    diffs = {}
    diff_order = []
    for diff in metric.get("differences") or []:
        if isinstance(diff, dict) and isinstance(diff.get("arm"), str) and diff["arm"] not in diffs:
            diffs[diff["arm"]] = diff
            diff_order.append(diff["arm"])
    control_names = {a["name"] for a in arms if a.get("control")} or {"control"}
    arm_names = [a["name"] for a in arms if a["name"] not in control_names]
    for name in diff_order:
        if name not in arm_names and name not in control_names:
            arm_names.append(name)

    def oriented(v):
        return -v if better == "lower" else v

    points = []
    for name in arm_names:
        diff = diffs.get(name)
        overall = diff.get("overall") if isinstance(diff, dict) and isinstance(diff.get("overall"), dict) else {}
        estimate = overall.get("estimate")
        if as_number(estimate) and math.isfinite(estimate):
            points.append(oriented(estimate))
            if _valid_interval(overall.get("interval")):
                points.extend(oriented(v) for v in overall["interval"])
    domain = max((abs(p) for p in points), default=0) or 1

    def pct(v):
        return 50 + (v / domain) * 47

    rows = []
    for name in arm_names:
        diff = diffs.get(name)
        overall = diff.get("overall") if isinstance(diff, dict) and isinstance(diff.get("overall"), dict) else {}
        estimate = overall.get("estimate")
        if not as_number(estimate) or not math.isfinite(estimate):
            rows.append(
                f'<div class="diff-row is-unmeasured"><span class="diff-arm">{e(name)}</span>'
                '<span class="diff-track" aria-hidden="true"></span>'
                '<span class="diff-value">not measured</span>'
                f'<span class="sr-only">{e(name)}: not measured</span></div>'
            )
            continue
        interval = overall.get("interval") if _valid_interval(overall.get("interval")) else None
        verdict, verdict_phrase = _diff_verdict(estimate, better)
        est_text = experiment_difference(estimate, metric)
        int_text = experiment_difference_interval(interval, metric)
        value_text = f"{est_text}, {int_text}" if interval else f"{est_text}, interval unavailable"
        whisker = ""
        if interval:
            lo, hi = sorted(oriented(v) for v in interval)
            whisker = f'<span class="diff-whisker" style="left:{pct(lo):.2f}%;width:{max(pct(hi) - pct(lo), 0.5):.2f}%"></span>'
        rows.append(
            f'<div class="diff-row is-{verdict}"><span class="diff-arm">{e(name)}</span>'
            f'<span class="diff-track" aria-hidden="true">{whisker}'
            f'<span class="diff-point" style="left:{pct(oriented(estimate)):.2f}%"></span></span>'
            f'<span class="diff-value">{e(value_text)} <span class="diff-verdict">({e(verdict)})</span></span>'
            f'<span class="sr-only">{e(name)}: {e(est_text)} difference from control, '
            f'{e(int_text)}, {e(verdict_phrase)}</span></div>'
        )
    if better in ("higher", "lower"):
        left, right = "← worse", "better →"
    else:
        left, right = "← lower", "higher →"
    return (
        f'<section class="diff-metric"><h4>{e(label)} '
        f'<span class="diff-kind">{e(kind_label)}</span></h4>'
        f'<p class="diff-axis" aria-hidden="true"><span>{left}</span><span>control (0)</span><span>{right}</span></p>'
        f'<div class="diff-rows">{"".join(rows)}</div></section>'
    )


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


def render_experiments_page(data, snapshot_date, picker=None, banner="", archive_month=None, url=None, root=None):
    if picker is None:
        picker = analytics_page.picker_html(_analytics_base(root), "experiments", "experiments.json", archive_month)
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        sys.exit("experiments.json: expected schema_version 1")
    if not isinstance(data.get("experiments"), list):
        sys.exit("experiments.json: expected experiments array")
    e = html.escape
    sections, links = [], []
    for experiment in data["experiments"]:
        if not isinstance(experiment, dict) or experiment.get("status") != "concluded":
            continue
        # Only public, sanitized narrative fields from analytics_snapshot.py are used.
        name = experiment.get("name") or "Unnamed experiment"
        question = experiment.get("hypothesis") or "Question unavailable in this snapshot."
        since, until = (experiment_stamp(experiment.get(key)) for key in ("started_at", "as_of"))
        if datetime.datetime.fromisoformat(since.replace("Z", "+00:00")) > datetime.datetime.fromisoformat(until.replace("Z", "+00:00")):
            sys.exit("experiments.json: observation window ends before it starts")
        anchor = f"experiment-{len(sections) + 1}"
        links.append(f'<a href="#{anchor}">{e(name)}</a>')
        arms = [arm for arm in experiment.get("arms", []) if isinstance(arm, dict) and isinstance(arm.get("name"), str)]
        arm_names = {arm["name"] for arm in arms}
        arm_items = []
        for arm in arms:
            mix = ", ".join(
                f'{e(row["crew"])} ({experiment_count(row.get("tasks"))} tasks)'
                for row in arm.get("crew_mix", [])
                if isinstance(row, dict) and isinstance(row.get("crew"), str)
                and not gap_identity(row["crew"], row.get("model"))
            )
            flags = [label for key, label in (("control", "control"), ("drifted", "drifted")) if arm.get(key)]
            if arm.get("retired_segment") is not None:
                flags.append("retired")
            arm_items.append(
                f'<li><strong>{e(arm["name"])}</strong>'
                + (f' ({", ".join(flags)})' if flags else "")
                + f' · {experiment_count(arm.get("n"))} enrolled tasks'
                + (f' · Observed crews: {mix}' if mix else "") + '</li>'
            )
        verdict = experiment.get("verdict") or {}
        verdict_text = verdict.get("label") or verdict.get("state") or "Unavailable"
        state = verdict.get("state")
        if state and state != verdict_text:
            verdict_text += f" ({state})"
        chosen = experiment.get("concluded_arm")
        choice = e(chosen) if isinstance(chosen, str) and chosen in arm_names else "None recorded"
        recommended = verdict.get("arm")
        recommendation = f'<p>Statistical recommendation: {e(recommended)}.</p>' if isinstance(recommended, str) and recommended in arm_names else ""
        reasons = "".join(f'<li>{e(reason)}</li>' for reason in verdict.get("reasons", []) if isinstance(reason, str))
        metrics = [metric for metric in experiment.get("metrics", []) if isinstance(metric, dict) and metric.get("metric") in EXPERIMENT_METRICS]
        primary = [metric for metric in metrics if metric["metric"] == experiment.get("primary_metric")]
        primary_ids = {id(m) for m in primary}
        guardrails = [m for m in metrics if id(m) not in primary_ids and not m.get("exploratory")]
        exploratory = [m for m in metrics if id(m) not in primary_ids and m.get("exploratory")]
        chart_parts = [experiment_diff_metric(m, arms, "Primary") for m in primary]
        chart_parts += [experiment_diff_metric(m, arms, "Guardrail") for m in guardrails]
        if exploratory:
            chart_parts.append(
                f'<details class="diff-exploratory"><summary>Other metrics ({len(exploratory)})</summary>'
                + "".join(experiment_diff_metric(m, arms, "Exploratory") for m in exploratory) + '</details>'
            )
        chart_html = (
            '<div class="diff-chart">' + "".join(chart_parts) + '</div>'
            if chart_parts else '<p class="empty">Difference from control unavailable.</p>'
        )
        raw_html = (
            '<details class="experiment-raw"><summary>Raw per-arm outcomes</summary>'
            + "".join(experiment_metric_table(metric, arms) for metric in metrics) + '</details>'
        ) if metrics else ""
        sections.append(f'''<section class="board experiment" id="{anchor}">
<h2>{e(name)} <span class="board-label">Concluded</span></h2>
<h3>Question</h3><p class="question">{e(question)}</p>
{render_window(since, until)}
<p class="board-note">Cumulative observations from experiment start to readout, not a rolling 30-day window.</p>
<div class="experiment-decision"><p><strong>Verdict:</strong> {e(verdict_text)}.</p>
<p><strong>Chosen arm:</strong> {choice}.</p>{recommendation}
{f'<ul>{reasons}</ul>' if reasons else ''}</div>
<h3>Arms</h3><ul>{''.join(arm_items)}</ul>
<h3>Difference from control</h3>{chart_html}{raw_html}
</section>''')
    body = f'''<article class="analytics experiments">
<h1>Concluded experiments</h1>
{banner}{picker}
<p class="summary">Questions, per-arm outcomes and decisions from Orbit's concluded experiments.</p>
<p class="as-of">Snapshot {e(snapshot_date)}. Built from the committed daily snapshot; no live Orbit calls.</p>
<p class="board-note">Concluded is a lifecycle state, not proof of a winner. A verdict may be withheld, collecting or inconclusive, and a chosen arm may be absent. Intervals are copied from the readout; unavailable values are not zero. Support is specific to each metric; open regression windows can leave outcomes unsettled. These are experiment outcomes, not ranked crew scorecards. See the <a href="/notes/crew-rankings-method/">method and caveats</a>.</p>
<nav class="board-nav" aria-label="Experiments">{' '.join(links)}</nav>
{''.join(sections) if sections else '<p class="empty">No concluded experiments in this snapshot.</p>'}
</article>'''
    return page(
        "Concluded experiments — Constellation Works",
        "Questions, arms, aggregate outcomes, intervals and decisions from concluded Orbit experiments.",
        url or f"{SITE}/analytics/experiments/", body, current="analytics",
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
        ("agents", "Agents", "Crew rankings for implementers, reviewers and pilots."),
        ("metrics", "Metrics", "Task outcomes, duration, cost and other delivery measures."),
        ("reliability", "Reliability", "Run outcomes and failure rates across the fleet."),
        ("experiments", "Experiments", "Results and observations from concluded experiments."),
    )
    items = "\n".join(
        f'<li><div><h2><a href="/analytics/{slug}/">{title}</a></h2>'
        f'<p>{description}</p></div></li>'
        for slug, title, description in cards
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
    build_agents()
    analytics_page.build(ROOT)
    build_reliability()
    build_experiments()


if __name__ == "__main__":
    main()
