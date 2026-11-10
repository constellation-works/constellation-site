#!/usr/bin/env python3
"""Build the Notes section and the public analytics pages.

Each note is a directory under notes/ holding index.md (front matter plus Markdown)
and any files the note links to (data, images). Output is a page per note, a
/notes/ index and an Atom feed. public/notes/ is generated: do not edit or commit it.

/ranking/ is rendered from the newest data/analytics/<YYYY-MM-DD>/ snapshot only (its
scorecards.json, and rank.json when the snapshot has one); it has no archive. It replaced
/analytics/agents/, whose URLs public/_redirects sends to /ranking/.
/analytics/metrics/ is rendered from the newest data/analytics/<YYYY-MM-DD>/metrics.json
via analytics_page.py. public/analytics/ and public/ranking/ are generated too: do not
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
              crew-ranking byline, `<crew@effort> (<model>), MVP of the week, <score>`
              (the crew labelled as on the boards, e.g. `opus · effort unknown`), is one author.
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
# A weekly crew-ranking byline is one author, though it has commas. Notes published
# before ORB-23846 name an estimated effort as `haiku@xhigh (est.)`; that mark stays valid.
MVP_BYLINE = re.compile(r"[^,()]+(?: \(est\.\))? \([^()]+\), MVP of the week, [^,]+")
VICTORY_PLACEHOLDER = "{{victory-address}}"
CREWS_EMBED = re.compile(r"<!-- crews-by-role: (\S+) -->")
CREWS_DATA = re.compile(r"data/crew-rankings/\d{4}-\d{2}-\d{2}")


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
    author = meta.get("author", "")
    meta["authors"] = (
        [author] if MVP_BYLINE.fullmatch(author)
        else [a.strip() for a in author.split(",") if a.strip()]
    ) or ["Constellation Works"]
    if meta.get("image") and not (path.parent / meta["image"]).is_file():
        sys.exit(f"{path}: image {meta['image']} not found")
    meta["slug"] = path.parent.name
    meta["body"] = text[m.end():]
    if meta["status"] == "published" and VICTORY_PLACEHOLDER in meta["body"]:
        sys.exit(f"{path}: the victory address is still the {VICTORY_PLACEHOLDER} placeholder; "
                 "the MVP crew writes it before the note is published")
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
      <a href="/ranking/">Ranking</a>
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
    if current in ("ranking", "analytics"):
        header = header.replace(f'href="/{current}/"', f'href="/{current}/" aria-current="page"', 1)
    return header


def page(title, description, url, body, image=None, draft=False, kind="website", current="notes",
         extra_css=(), extra_js=()):
    e = html.escape
    js = "".join(f'\n<script src="{asset(name)}" defer></script>' for name in extra_js)
    img = image or f"{SITE}/brand/png/cw-lockup-light-1520.png"
    robots = '<meta name="robots" content="noindex">\n' if draft else ""
    extra_links = "".join(f'<link rel="stylesheet" href="{asset(name)}">\n' for name in extra_css)
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
{extra_links}<script src="{asset('theme-init.js')}"></script>
</head>
<body>
{header_html(current)}
<main class="wrap">
{body}
</main>
{FOOTER}{js}
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


def embed_crews_by_role(body, path):
    """Replace each crews-by-role marker with the /ranking/ page's own component.

    Returns the body and whether it embedded one (the page then loads the
    component's stylesheet and script, analytics.css and analytics.js).
    """
    found = False

    def swap(match):
        nonlocal found
        rel = match.group(1)
        directory = ROOT / rel
        if not CREWS_DATA.fullmatch(rel) or not (directory / "scorecards.json").is_file():
            sys.exit(f"{path}: crews-by-role needs data/crew-rankings/<YYYY-MM-DD> with a scorecards.json, got {rel!r}")
        found = True
        return f'<div class="analytics crews-embed">\n{render_crews_by_role(directory)}\n</div>'

    return CREWS_EMBED.sub(swap, body), found


def build_note(note):
    e = html.escape
    url = f"{SITE}/notes/{note['slug']}/"
    image = f"{url}{note['image']}" if note.get("image") else None
    src = SRC / note["slug"]
    # Everything beside index.md is published; the link card is not listed as data.
    files = sorted(f for f in src.iterdir() if f.is_file() and f.name != "index.md")
    data = [f for f in files if f.name != note.get("image")]
    text, embedded = embed_crews_by_role(render_body(note["body"]), src / "index.md")
    # The rail comes last so narrow screens list the data after the text; wide screens
    # still place it in the margin beside the title (grid-row in notes.css).
    body = f"""<article class="note">
<h1>{e(note['title'])}</h1>
{meta_block(note)}
<p class="summary">{e(note['summary'])}</p>
{text}
{rail(note, data)}
</article>"""
    dest = OUT / note["slug"]
    dest.mkdir(parents=True)
    for f in files:
        shutil.copy2(f, dest / f.name)
    title = f"{note['title']} — Constellation Works"
    (dest / "index.html").write_text(
        page(title, note["summary"], url, body, image, note["status"] == "draft", "article",
             extra_css=("analytics.css",) if embedded else (),
             extra_js=("analytics.js",) if embedded else ()),
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
# Orbit's attribution for system-run work, not a configured crew. Rank crew
# lists never show it. It is not a scorecard gap sentinel (those are GAP_CREWS).
RANK_NON_CREW = "system"
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


def plural(count, word, words=None):
    return word if count == 1 else (words or word + "s")


def lower_first(text):
    return text[:1].lower() + text[1:]


def join_words(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def render_window(since, until):
    e = html.escape
    return (
        f'<p class="board-window">Window <time datetime="{e(since)}">{e(since)}</time>'
        f' to <time datetime="{e(until)}">{e(until)}</time> UTC.</p>'
    )


def friendly_window(since, until):
    """`<time>` pair for a window: 9 Oct – 8 Nov 2026, exact stamps in datetime."""
    e = html.escape
    try:
        start, end = analytics_page.parse_time(since), analytics_page.parse_time(until)
    except ValueError:
        return f'<time datetime="{e(since)}">{e(since)}</time> – <time datetime="{e(until)}">{e(until)}</time>'
    first = f"{start.day} {start.strftime('%b')}" + ("" if start.year == end.year else f" {start.year}")
    return (
        f'<time datetime="{e(since)}">{first}</time> – '
        f'<time datetime="{e(until)}">{end.day} {end.strftime("%b %Y")}</time> UTC'
    )


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


def _analytics_base(root=None):
    return (pathlib.Path(root) if root is not None else ROOT) / "data" / "analytics"


# ---------- /ranking/: model rank, overall index and crews by role ----------

# The All-roles index on the Overall tab. Each role's score is divided by its
# fleet average (100 = average), crews pooled into their model by units, and
# the indexes are averaged with these weights (Daniel's defaults, ORB-23594).
# A missing role is never imputed (ORB-23668): a model needs a ranked crew in
# at least `min_roles` roles, and its index is the weighted mean over the roles
# it holds, the weights rescaled to sum to 1. Change them here and the page and
# its stated rule follow.
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
    """(ranked, not ranked) model rows, gaps removed; ranked rows in rank order."""
    rows = [
        row for row in rank.get("rows") or []
        if isinstance(row, dict) and isinstance(row.get("model"), str)
        and row["model"] not in GAP_MODELS and as_number(row.get("units"))
    ]
    ranked = [row for row in rows if isinstance(row.get("rank"), int) and not isinstance(row.get("rank"), bool)
              and row.get("eligible") is True and as_number(row.get("score"))]
    ranked.sort(key=lambda row: row["rank"])
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

    ``system`` and attribution gaps are omitted. A key that already carries
    an effort (``sol@high``) is that recorded label. A bare key has no recorded
    effort, so it reads ``crew · effort unknown``; a snapshot's
    ``effort_estimate`` (written before ORB-23846) is ignored.
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
        label = crew if "@" in crew else f"{crew} · effort unknown"
        if label in index:
            slot = out[index[label]]
            if tasks is not None:
                slot["tasks"] = tasks if slot["tasks"] is None else slot["tasks"] + tasks
            continue
        index[label] = len(out)
        out.append({"label": label, "tasks": tasks})
    return out


def rank_crew_line(row):
    """One model's rank crews on one line (``sol@high · sol@xhigh``)."""
    return " · ".join(item["label"] for item in rank_crew_entries(row))


def podium_from_rank(rank):
    """The podium's top three from Model rank, in Rank's order, with their Rank score."""
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
    """A model's crews on one line; commas once the labels carry efforts (``sol@high, sol · effort unknown``)."""
    return (", " if row.get("labelled") else " · ").join(row["crews"])


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
    values = [100.0]
    for row in ranked:
        interval = row.get("interval") or {}
        for value in (interval.get("p10"), interval.get("p90"), row.get("score")):
            if as_number(value):
                values.append(value)
    low = math.floor(min(values) / 10) * 10 - 5
    high = math.ceil(max(values) / 10) * 10 + 5
    step = 10 if high - low <= 80 else 20
    ticks = list(range(int(math.ceil(low / step) * step), int(high) + 1, step))
    return low, high, ticks


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
        f'<ul class="contribs">{"".join(measures)}</ul>{shrink}</div>'
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
            f'<span style="left:{axis_pct(tick, low, high):.2f}%">{tick}</span>' for tick in ticks
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
                whisker = f'<span class="whisker prov-{provider(row["model"])}" style="left:{left:.2f}%;width:{max(right - left, 0.5):.2f}%"></span>'
            point = f'<span class="whisker-point prov-{provider(row["model"])}" style="left:{axis_pct(row["score"], low, high):.2f}%"></span>'
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
                f'<span aria-hidden="true">{whisker}{point}</span><span class="sr-only">{e(interval_sr)}</span></span>'
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
<p class="board-key">p10–p90 whisker on a shared score axis · <span class="k-fleet" aria-hidden="true"></span> 100 is the fleet</p></div>
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


def crew_role_bodies(scorecards):
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
        "implementers": (impl, takeaways + implementers_overall(impl) + heatmap),
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
    headings, so it is never restyled per view (STD-07 §R30). Neither form draws
    a role toggle. It reads only the directory's scorecards.json.
    """
    if role is not None and role not in ROLE_ORDER:
        sys.exit(f"crews by role: unknown role {role!r}")
    return crews_by_role_html(crew_role_bodies(load_scorecards(directory)), role)


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
        extra_css=("analytics.css",), extra_js=("analytics.js",),
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

    In particular, source, activities, observed_states and arbitrary
    future diagnostic fields have no route into the public HTML.
    Per-job breakdowns use reliability_by_job, which validates job ids and
    recomputes rates from counts.
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


# Job ids are snapshot-controlled vocabulary. Only SAFE_JOB_ID values reach the
# page; anything else is dropped before rendering, the same allowlist rule the
# snapshot applies when it sums by_job across workspaces.
SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9_@.+-]{1,80}$")
JOB_LABELS = {
    "task_pr_pipeline": "PR delivery",
    "task_pilot_pipeline": "Pilot delivery",
    "ci_failure_sweep_pipeline": "CI failure sweep",
    "task_auto_pipeline": "Auto delivery",
    "task_landing_pipeline": "Landing",
    "agent_explore_pipeline": "Agent explore",
    "task_gate_pipeline": "Task gate",
    "escalation_triage_pipeline": "Escalation triage",
    "workspace_auto_pipeline": "Workspace auto",
    "ux_rules_pipeline": "UX rules",
    "image_input_probe_pipeline": "Image input probe",
    "task_local_pipeline": "Local delivery",
    "worktree_gc_pipeline": "Worktree GC",
    "blocked_task_recovery_pipeline": "Blocked task recovery",
    "finding_verification_pipeline": "Finding verification",
    "crew_performance_refresh_pipeline": "Crew performance refresh",
    "dependabot_alert_sweep_pipeline": "Dependabot sweep",
    "baseline_hold_refresh_pipeline": "Baseline hold refresh",
    "resident_cycle_pipeline": "Resident cycle",
    "store_gc_pipeline": "Store GC",
    "agent_invoke_pipeline": "Agent invoke",
    "workspace_pull_pipeline": "Workspace pull",
    "review_evidence_fulfilment_pipeline": "Review evidence",
    "task_publication_pipeline": "Task publication",
    "evolution_pass_pipeline": "Evolution pass",
    "orb20863_visual_eval": "Visual eval",
}


def job_label(job_id):
    """Human-readable name for a job id, falling back to the raw id."""
    return JOB_LABELS.get(job_id, job_id)


def reliability_by_job(data):
    """Validated per-job aggregates for the public page.

    Drops rows whose job id fails SAFE_JOB_ID or whose counts are not exact
    non-negative integers, recomputes each failure rate from counts (never the
    snapshot's supplied rate), keeps only the snapshot's boolean low_sample
    flag, and sorts by failures then total, as the snapshot orders them.
    """
    rows = data.get("by_job") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    jobs = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        job = row.get("job_id")
        if not isinstance(job, str) or not SAFE_JOB_ID.fullmatch(job):
            continue
        counts = row.get("counts")
        if not isinstance(counts, dict):
            continue
        valid = {}
        ok = True
        for key in ("succeeded", "failed", "total"):
            value = counts.get(key)
            if type(value) is not int or value < 0:
                ok = False
                break
            valid[key] = value
        if not ok:
            continue
        denominator = valid["succeeded"] + valid["failed"]
        rate = valid["failed"] / denominator if denominator else None
        supplied = row.get("failure_rate")
        low = isinstance(supplied, dict) and supplied.get("low_sample") is True
        jobs.append({
            "job_id": job,
            "label": JOB_LABELS.get(job, job),
            "succeeded": valid["succeeded"],
            "failed": valid["failed"],
            "total": valid["total"],
            "denominator": denominator,
            "rate": rate,
            "low": low,
        })
    jobs.sort(key=lambda job: (-job["failed"], -job["total"], job["job_id"]))
    return jobs


HOT_JOB_RATE = 0.05
SPIKE_MIN_RATE = 0.05
SPIKE_FACTOR = 1.5
MONTH_DAY = "%b"


def pct(part, whole, places=2):
    return f"{part / whole:.{places}%}" if whole else "Unavailable"


def short_pct(rate):
    """Two decimals under 1%, one above: 0.08%, 7.7%."""
    if rate is None:
        return "Unavailable"
    return f"{rate:.2%}" if rate < 0.01 else f"{rate:.1%}"


def reliability_recovery(data):
    """totals.recovery.per_job_run as (numerator, denominator), counts only."""
    totals = data.get("totals")
    recovery = totals.get("recovery") if isinstance(totals, dict) else None
    per_run = recovery.get("per_job_run") if isinstance(recovery, dict) else None
    if not isinstance(per_run, dict):
        return None
    numerator, denominator = per_run.get("numerator"), per_run.get("denominator")
    if type(numerator) is not int or type(denominator) is not int or numerator < 0 or denominator <= 0:
        return None
    if numerator > denominator:
        return None
    return numerator, denominator


def reliability_days(data, since, until):
    """Validated daily buckets from over_time, rates recomputed from counts.

    A bucket that starts before the window opens or ends after it closes is a
    partial day. Rows with a bad stamp or counts are dropped, never guessed.
    """
    rows = data.get("over_time") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    opened = analytics_page.parse_time(since)
    closed = analytics_page.parse_time(until)
    days = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        start, end = row.get("bucket_start"), row.get("bucket_end")
        if not isinstance(start, str) or not isinstance(end, str):
            continue
        if not UTC_STAMP.fullmatch(start) or not UTC_STAMP.fullmatch(end):
            continue
        try:
            begins, ends = analytics_page.parse_time(start), analytics_page.parse_time(end)
        except ValueError:
            continue
        if ends <= begins:
            continue
        counts = row.get("counts")
        if not isinstance(counts, dict):
            continue
        succeeded, failed = counts.get("succeeded"), counts.get("failed")
        if type(succeeded) is not int or type(failed) is not int or succeeded < 0 or failed < 0:
            continue
        settled = succeeded + failed
        days.append({
            "start": start,
            "begins": begins,
            "failed": failed,
            "settled": settled,
            "rate": failed / settled if settled else None,
            "partial": begins < opened or ends > closed,
        })
    days.sort(key=lambda day: day["begins"])
    return days


def day_label(day):
    return f"{day['begins'].day} {day['begins'].strftime(MONTH_DAY)}"


def daily_chart(days, overall_rate):
    """Failure rate per UTC day as HTML bars, with a 30-day reference line,
    a settled-runs strip, spike labels and a per-day text alternative."""
    e = html.escape
    rated = [day["rate"] for day in days if day["rate"] is not None]
    if not rated:
        return '<p class="empty">No daily buckets in this window.</p>'
    top = max(rated + ([overall_rate] if overall_rate is not None else []))
    # Headroom above the tallest bar for its spike label.
    scale = max(0.02, math.ceil(top * 1.15 * 100 / 2) * 2 / 100)
    volume_top = max(day["settled"] for day in days) or 1
    # Rounded to the precision the note prints, so 1.5 x 20% labels a 30% day.
    threshold = round(max(SPIKE_MIN_RATE, (overall_rate or 0) * SPIKE_FACTOR), 3)
    bars, volumes, ticks = [], [], []
    for index, day in enumerate(days):
        rate = day["rate"]
        label = day_label(day)
        partial = " (partial day)" if day["partial"] else ""
        if rate is None:
            text = f"{label}: unavailable, no settled runs{partial}"
        else:
            text = f"{label}: {rate:.2%} · {day['failed']:,} failed of {day['settled']:,} settled{partial}"
        spike = rate is not None and rate >= threshold
        height = 0 if rate is None else max(1.5, rate / scale * 100)
        state = (" is-partial" if day["partial"] else "") + (" is-spike" if spike else "")
        spike_label = f'<span class="day-label" aria-hidden="true">{short_pct(rate)}</span>' if spike else ""
        bars.append(
            f'<li class="day{state}" title="{e(text)}" style="--h:{height:.1f}%">'
            f'{spike_label}<span class="day-bar"></span><span class="sr-only">{e(text)}</span></li>'
        )
        volume = max(4.0, day["settled"] / volume_top * 100)
        volumes.append(f'<span class="{state.strip()}"><span style="height:{volume:.1f}%"></span></span>')
        tick = label if index % 5 == 0 or index == len(days) - 1 else ""
        ticks.append(f"<span>{e(tick)}</span>")
    reference = ""
    if overall_rate is not None:
        reference = (
            f'<span class="day-ref" aria-hidden="true" style="bottom:{min(100.0, overall_rate / scale * 100):.1f}%">'
            f'<span>{overall_rate:.2%}</span></span>'
        )
    peak = max(days, key=lambda day: (day["settled"], day["begins"]))
    partial_days = [day for day in days if day["partial"]]
    partial_note = (
        f" Faded: partial days ({join_words(day_label(day) for day in partial_days)}), where the window "
        "opens or closes mid-day." if partial_days else ""
    )
    table_rows = "".join(
        f'<tr><td data-label="Day"><time datetime="{e(day["start"])}">{e(day_label(day))}</time>'
        f'{" (partial)" if day["partial"] else ""}</td>'
        f'<td class="num" data-label="Failure rate">{e(pct(day["failed"], day["settled"]))}</td>'
        f'<td class="num" data-label="Failed">{day["failed"]:,}</td>'
        f'<td class="num" data-label="Settled runs">{day["settled"]:,}</td></tr>'
        for day in reversed(days)
    )
    table_html = (
        '<details class="more"><summary>Daily figures as a table</summary><div class="table"><table>'
        '<caption class="sr-only">Failure rate by UTC day, newest first</caption>'
        '<thead><tr><th scope="col">Day</th><th scope="col" class="num">Failure rate</th>'
        '<th scope="col" class="num">Failed</th><th scope="col" class="num">Settled runs</th></tr></thead>'
        f'<tbody>{table_rows}</tbody></table></div></details>'
    )
    return (
        '<div class="daychart-box"><div class="daychart-grid">'
        f'<div class="daychart-axis" aria-hidden="true"><span>{scale:.0%}</span><span>0%</span></div>'
        f'<div class="daychart-plot">{reference}'
        f'<ol class="daychart" aria-label="Failure rate by UTC day, oldest first">{"".join(bars)}</ol></div>'
        f'<div class="day-vols" aria-hidden="true">{"".join(volumes)}</div>'
        f'<div class="day-ticks" aria-hidden="true">{"".join(ticks)}</div></div>'
        f'<p class="daychart-note">Grey strip: settled runs per day (peak {peak["settled"]:,} on {e(day_label(peak))}). '
        f'Labelled bars are at least {threshold:.1%}.{e(partial_note)}</p>'
        f'</div>{table_html}'
    )


def reliability_by_job_section(jobs, total_failed):
    """Failures by job: bars by count or by rate, small samples marked."""
    e = html.escape
    failing = [job for job in jobs if job["failed"] > 0]
    clean = [job for job in jobs if job["failed"] == 0]
    head = (
        '<div class="board-head"><h2 id="by-job-title">Failures by job</h2>'
        '<div class="board-toggle job-sort" role="group" aria-label="Sort jobs" hidden>'
        '<button type="button" aria-pressed="true" data-sort="count">Most failures</button>'
        '<button type="button" aria-pressed="false" data-sort="rate">Highest rate</button></div></div>'
    )
    intro = (
        '<p class="score-key">Rate = direct failures ÷ settled runs (successes plus direct failures) for '
        "each job, all workspaces combined. The counts and percentages name the rate, not colour alone.</p>"
    )
    if not failing:
        return (
            f'<section class="board" id="by-job" aria-labelledby="by-job-title">{head}{intro}'
            '<p class="empty">No job failures in this window.</p>'
            + clean_jobs(clean) + "</section>"
        )
    max_failed = max(job["failed"] for job in failing)
    sized = [job["rate"] for job in failing if job["rate"] is not None and not job["low"]]
    max_rate = max(sized, default=None) or max((job["rate"] or 0 for job in failing), default=0) or 1
    rows = []
    for order, job in enumerate(failing):
        rate = job["rate"]
        hot = rate is not None and rate >= HOT_JOB_RATE and not job["low"]
        tag = "small sample" if job["low"] else (f"above {HOT_JOB_RATE:.0%}" if hot else "")
        w_count = max(0.5, job["failed"] / max_failed * 100)
        w_rate = max(0.5, min(100.0, (rate or 0) / max_rate * 100))
        tone = "is-low" if job["low"] else ("is-hot" if hot else "")
        rows.append(
            f'<tr class="job {tone}" data-order="{order}" data-failed="{job["failed"]}" '
            f'data-rate="{rate if rate is not None else -1:.6f}" data-low="{1 if job["low"] else 0}">'
            f'<th scope="row" data-label="Job"><span class="job-name">{e(job["label"])}</span>'
            f'<span class="job-tag">{e(tag)}</span></th>'
            f'<td class="bar-cell job-bar-cell" data-label="Bar"><span class="job-bar" aria-hidden="true">'
            f'<span class="job-fill" style="--w-count:{w_count:.1f}%;--w-rate:{w_rate:.1f}%"></span></span></td>'
            f'<td class="num job-rate" data-label="Rate">{e(short_pct(rate))}</td>'
            f'<td class="num" data-label="Failed">{job["failed"]:,}</td>'
            f'<td class="num" data-label="Settled runs">{job["denominator"]:,}</td></tr>'
        )
    top = failing[0]
    share = f" {e(top['label'])} accounts for {top['failed'] / total_failed:.0%} of all direct failures." if total_failed else ""
    notes = (
        f'<p class="board-note sort-note" data-sort-note="count">Sorted by failed runs.{share}</p>'
        '<p class="board-note sort-note" data-sort-note="rate" hidden>Sorted by failure rate. '
        "Small samples, as the snapshot flags them, sink to the bottom.</p>"
    )
    table_html = (
        '<div class="table"><table class="bar-table jobs" data-sort="count">'
        '<caption class="sr-only">Direct failures by job</caption>'
        '<thead><tr><th scope="col">Job</th><th scope="col"><span class="when-count">Failed runs</span>'
        '<span class="when-rate">Failure rate</span></th><th scope="col" class="num">Rate</th>'
        '<th scope="col" class="num">Failed</th><th scope="col" class="num">Settled runs</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )
    return (
        f'<section class="board" id="by-job" aria-labelledby="by-job-title">{head}{intro}{notes}'
        f"{table_html}{clean_jobs(clean)}</section>"
    )


def clean_jobs(clean):
    if not clean:
        return ""
    count = len(clean)
    items = " · ".join(
        f'{html.escape(job["label"])} ({job["denominator"]:,})' for job in clean
    )
    return (
        f'<details class="more"><summary>{count} {plural(count, "job")} with no failures</summary>'
        f'<p class="board-note">{items}</p><p class="board-note">Settled runs in brackets.</p></details>'
    )


OUTCOME_MIX = (
    ("succeeded", "Succeeded", "mix-ok", "Counted in the success rate"),
    ("failed", "Direct failures", "mix-fail", "Counted in the failure rate"),
    ("cascaded", "Cascaded failures", "mix-echo", "Echoes of a direct failure; not rated"),
    ("other", "Other outcomes", "mix-other", "Held, cancelled, paused, in flight; not rated"),
)
OTHER_KEYS = ("held", "cancelled", "upgrade_paused", "in_flight", "skipped", "unknown")


def render_reliability_page(data, snapshot_date, picker=None, banner="", archive_month=None, url=None, root=None):
    if picker is None:
        picker = analytics_page.picker_html(_analytics_base(root), "reliability", "reliability.json", archive_month)
    if not isinstance(snapshot_date, str) or not DATE_DIR.fullmatch(snapshot_date):
        sys.exit("reliability snapshot date must be YYYY-MM-DD")
    e = html.escape
    counts, (since, until) = reliability_aggregates(data)
    total = counts["total"]
    settled = counts["succeeded"] + counts["failed"]
    other = sum(counts[key] for key in OTHER_KEYS)
    rate = counts["failed"] / settled if settled else None
    outcomes = dict(RELIABILITY_OUTCOMES)

    headline = (
        '<div class="rel-hero"><span class="tile-head">Settled runs that succeeded</span>'
        f'<span class="rel-big">{e(pct(counts["succeeded"], settled))}</span>'
        f'<span class="rel-sub">{counts["succeeded"]:,} of {settled:,} · '
        f'<span class="is-worse">{counts["failed"]:,}</span> failed directly</span></div>'
    )
    recovery = reliability_recovery(data)
    if recovery:
        recovery_tile = (
            f'{e(pct(recovery[0], recovery[1], 1))}',
            f"{recovery[0]:,} of {recovery[1]:,} job runs with steps",
        )
    else:
        recovery_tile = ("Unavailable", "no recovery figures in this snapshot")
    other_parts = [
        f"{counts['held']:,} held", f"{counts['cancelled']:,} cancelled",
        f"{counts['upgrade_paused'] + counts['in_flight']:,} paused or in flight",
    ]
    if counts["skipped"]:
        other_parts.append(f"{counts['skipped']:,} skipped")
    if counts["unknown"]:
        other_parts.append(f"{counts['unknown']:,} unknown")
    tiles = (
        ("recovery", "Needed recovery", *recovery_tile),
        ("cascaded", "Cascaded echoes", f"{counts['cascaded']:,}", "rolled into their origin, not counted twice"),
        ("other-outcomes", "Other outcomes", f"{other:,}", " · ".join(other_parts)),
    )
    tile_html = "".join(
        f'<li id="{key}"><div class="tile"><span class="tile-head">{e(label)}</span>'
        f'<span class="tile-value">{e(value)}</span><span class="tile-sub">{e(sub)}</span></div></li>'
        for key, label, value, sub in tiles
    )
    hero = (
        f'<section class="rel-top" id="settled" aria-label="Success and failure">{headline}'
        f'<ul class="tiles rel-tiles">{tile_html}</ul></section>'
    )

    mix_counts = {"succeeded": counts["succeeded"], "failed": counts["failed"],
                  "cascaded": counts["cascaded"], "other": other}
    aria = ", ".join(f"{pct(mix_counts[key], total)} {label.lower()}" for key, label, _cls, _note in OUTCOME_MIX)
    segments = "".join(
        f'<span class="mix-seg {cls}" style="flex-grow:{mix_counts[key]}"></span>'
        for key, _label, cls, _note in OUTCOME_MIX if mix_counts[key]
    )
    legend = "".join(
        f'<li><i class="{cls}" aria-hidden="true"></i><span><strong>{e(label)}</strong> '
        f'<span class="mix-n">{mix_counts[key]:,} · {e(pct(mix_counts[key], total))}</span>'
        f'<span class="mix-note">{e(note)}</span></span></li>'
        for key, label, cls, note in OUTCOME_MIX
    )
    every = reliability_table([(outcomes[key], counts[key]) for key, _label in RELIABILITY_OUTCOMES], total,
                              "Every outcome as a share of all recorded runs")
    mix = (
        '<section class="board" id="failures" aria-labelledby="failures-title">'
        f'<div class="board-head"><h2 id="failures-title">Where every run ended</h2>'
        f'<p class="board-key">Share of all {total:,} recorded runs</p></div>'
        + (f'<div class="mix-bar" role="img" aria-label="{e(aria)}">{segments}</div>' if total else "")
        + f'<ul class="mix-legend">{legend}</ul>'
        + f'<details class="more"><summary>Every outcome count</summary>{every}</details></section>'
    )

    days = reliability_days(data, since, until)
    daily = (
        '<section class="board" id="daily" aria-labelledby="daily-title">'
        '<div class="board-head"><h2 id="daily-title">Failure rate by day</h2>'
        '<p class="board-key">Direct failures ÷ settled runs per UTC day'
        + (f' · <span class="k-ref" aria-hidden="true"></span> 30-day rate {rate:.2%}' if rate is not None else "")
        + ' · faded = partial day</p></div>'
        + daily_chart(days, rate) + "</section>"
    )

    by_job = reliability_by_job_section(reliability_by_job(data), counts["failed"])

    method = '''<details class="more method" id="method"><summary>How these are counted</summary><ul>
<li>Settled runs = successes plus direct failures. Failure rates use this denominator, recomputed on this page from the counts.</li>
<li>A cascaded failure is a wrapper job echoing a failure that started in another job. It is rolled into the original, so it is not counted twice.</li>
<li>Held, cancelled, paused-for-upgrade, in-flight, skipped and unknown runs are outside the success and failure rates.</li>
<li>Recovery: a job run where any step needed a recovery attempt, out of runs with a recorded step invocation.</li>
<li>Days are UTC. The first and last days are partial when the 30-day window opens or closes mid-day.</li>
<li>Counts are as of the snapshot. Held and in-flight runs can settle in later snapshots. Rates describe observed outcomes, not causes, and are not a comparison of crews.</li>
</ul></details>'''
    empty = '<p class="empty">No recorded runs in this window. Rates are unavailable.</p>' if not total else ""
    body = f'''<article class="analytics reliability-page">
<h1>Reliability</h1>
{banner}{picker}
<p class="summary">Success, failure and other outcomes across the fleet over 30 days, from the daily public snapshot.</p>
<p class="window window-statement">Last 30 days · {friendly_window(since, until)}</p>
<p class="as-of">All workspaces · Snapshot {snapshot_date} · {total:,} recorded runs; {settled:,} settled outcomes.</p>
<p class="board-window">Exact window: <time datetime="{e(since)}">{e(since)}</time> to <time datetime="{e(until)}">{e(until)}</time> UTC.</p>
{empty}{hero}
{mix}
{daily}
{by_job}
{method}
</article>'''
    return page(
        "Reliability — Constellation Works",
        "Aggregate Orbit success and failure counts and rates over 30 days.",
        url or f"{SITE}/analytics/reliability/", body, current="analytics",
        extra_css=("analytics.css",), extra_js=("analytics.js",),
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


def _money_text(amount):
    """Fixed 2-decimal dollars, expanding precision when a non-zero amount
    would otherwise collapse to zero (mirrors the _plain signed-zero guard)."""
    if amount == 0:
        amount = 0
    text = f"{amount:,.2f}"
    if amount != 0 and float(text.replace(",", "")) == 0:
        for decimals in (4, 6, 8, 10):
            candidate = f"{amount:,.{decimals}f}".rstrip("0").rstrip(".")
            if candidate not in ("0", "-0", "", "-") and float(candidate.replace(",", "")) != 0:
                return candidate
        return f"{amount:.4g}"
    return text


def _money_line_text(amount):
    """Fixed 4-decimal dollars-per-line, expanding precision on collapse."""
    if amount == 0:
        amount = 0
    text = f"{amount:,.4f}"
    if amount != 0 and float(text.replace(",", "")) == 0:
        for decimals in (6, 8, 10):
            candidate = f"{amount:,.{decimals}f}".rstrip("0").rstrip(".")
            if candidate not in ("0", "-0", "", "-") and float(candidate.replace(",", "")) != 0:
                return candidate
        return f"{amount:.4g}"
    return text


def _points_text(points):
    """Fixed 1-decimal points, expanding precision on collapse."""
    if points == 0:
        points = 0
    text = f"{points:.1f}"
    if points != 0 and float(text) == 0:
        for decimals in (2, 3, 4, 6, 8, 10):
            candidate = f"{points:.{decimals}f}".rstrip("0").rstrip(".")
            if candidate not in ("0", "-0", "", "-") and float(candidate) != 0:
                return candidate
        return f"{points:.4g}"
    return text


def experiment_value(value, unit):
    if not as_number(value) or not math.isfinite(value):
        return "Unavailable"
    if value == 0:
        value = 0
    if unit == "%":
        return f"{_points_text(value * 100)}%"
    if unit == "USD":
        return f"${_money_text(value)}"
    if unit == "USD/line":
        return f"${_money_line_text(value)} / line"
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
        return f"{sign}{_points_text(a * 100)} points"
    if category == "money":
        return f"{sign}${_money_text(a)}"
    if category == "money_line":
        return f"{sign}${_money_line_text(a)} / line"
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


STATUS_LABEL = {
    "withheld": "Verdict withheld",
    "inconclusive": "Inconclusive",
    "collecting": "Collecting",
    "stopped-early": "Stopped early - no verdict",
}
STOPPED_EARLY_REASON = "Concluded before reaching the minimum sample; no verdict is available."


def _join_names(names):
    names = [name for name in names if name]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _lower_first(text):
    return text[:1].lower() + text[1:] if text else text


def _reason_html(reason):
    """Readout reasons quote arm and metric names in backticks; render them as code."""
    parts = html.escape(reason).split("`")
    return "".join(f"<code>{part}</code>" if index % 2 else part for index, part in enumerate(parts))


def _finite(value):
    return as_number(value) and math.isfinite(value)


def experiment_short_question(experiment, arms, metrics):
    """A one-line question assembled from the readout's own fields.

    The full hypothesis stays on the page; this is only the arms, the primary
    metric and its direction, the population and the guardrails, worded as a question.
    """
    treatment = [arm["name"] for arm in arms if not arm.get("control")]
    key = experiment.get("primary_metric")
    if not treatment or key not in EXPERIMENT_METRICS:
        return None
    metric = next((m for m in metrics if m.get("metric") == key), {})
    verb = {"lower": "lower", "higher": "raise"}.get(metric.get("better"), "change")
    label = _lower_first(EXPERIMENT_METRICS[key][0])
    population = experiment.get("population") if isinstance(experiment.get("population"), dict) else {}
    tiers = [t for t in population.get("complexity") or [] if isinstance(t, str)]
    scope = f" on {_join_names(tiers)} tasks" if tiers else ""
    definition = experiment.get("guardrail_definition")
    guards = [
        _lower_first(EXPERIMENT_METRICS[name][0])
        for name in (definition if isinstance(definition, dict) else {})
        if name in EXPERIMENT_METRICS
    ]
    guard_text = f", within the {_join_names(guards)} guardrails" if guards else ""
    lead = "Do" if len(treatment) > 1 else "Does"
    return f"{lead} {_join_names(treatment)} {verb} {label}{scope} compared with control{guard_text}?"


def experiment_fidelity(arm, treatment_count, warning_kinds):
    """(own, n) for a treatment arm: tasks that ran on the arm's own crew.

    The snapshot names no assigned crew, so the own crew is the observed crew
    named like the arm. A single treatment arm with no crew of its name falls
    back to enrolled tasks minus the readout's recorded crew mismatches.
    Returns None when neither rule applies.
    """
    n = arm.get("n")
    if type(n) is not int or n < 0:
        return None
    if n == 0:
        return 0, 0
    for row in arm.get("crew_mix") or []:
        if isinstance(row, dict) and row.get("crew") == arm["name"] and type(row.get("tasks")) is int:
            return row["tasks"], n
    mismatch = (warning_kinds or {}).get("crew_mismatch") if isinstance(warning_kinds, dict) else None
    if treatment_count == 1 and type(mismatch) is int and 0 <= mismatch <= n:
        return n - mismatch, n
    return None


def _experiment_cell(metric, diff, domain_points=None):
    """Classify one arm's difference from control. Clear only when the interval excludes zero."""
    better = metric.get("better") if metric.get("better") in ("higher", "lower") else None
    overall = diff.get("overall") if isinstance(diff, dict) and isinstance(diff.get("overall"), dict) else {}
    estimate = overall.get("estimate")
    if not _finite(estimate):
        return {"measured": False}
    interval = overall.get("interval") if _valid_interval(overall.get("interval")) else None
    clear = bool(interval) and (interval[0] > 0 or interval[1] < 0)
    if estimate == 0:
        kind, tag = "same", "Same"
        clear = False
    elif better is None:
        kind, tag = "neutral", "Higher" if estimate > 0 else "Lower"
        clear = False
    else:
        good = estimate < 0 if better == "lower" else estimate > 0
        if clear:
            kind, tag = ("better", "Better") if good else ("worse", "Worse")
        else:
            kind, tag = ("lean-better", "Leans better") if good else ("lean-worse", "Leans worse")
    sign = -1 if better == "lower" else 1
    return {
        "measured": True,
        "estimate": estimate,
        "interval": interval,
        "clear": clear,
        "kind": kind,
        "tag": tag,
        "oriented": [sign * estimate] + ([sign * v for v in interval] if interval else []),
        "text": experiment_difference(estimate, metric),
        "interval_text": experiment_difference_interval(interval, metric) if interval else "no interval",
        "short": _drop_unit(experiment_difference(estimate, metric), metric),
        "short_interval": _drop_unit(experiment_difference_interval(interval, metric), metric) if interval else "no interval",
    }


def _drop_unit(text, metric):
    """Scorecard cells sit under a row that names the unit; keep only short unit marks."""
    _, display = EXPERIMENT_METRICS.get(metric.get("metric"), ("", ""))
    text = text.replace(" points", " pts")
    for unit in (" tokens", " lines") + ((" " + display,) if display and display not in ("USD", "%", "hours", "minutes") else ()):
        text = text.replace(unit, "")
    return text


def experiment_metric_cells(metric, treatment):
    diffs = {}
    for diff in metric.get("differences") or []:
        if isinstance(diff, dict) and isinstance(diff.get("arm"), str) and diff["arm"] not in diffs:
            diffs[diff["arm"]] = diff
    return [_experiment_cell(metric, diffs.get(name)) for name in treatment]


def _cell_html(cell, arm_name):
    e = html.escape
    if not cell["measured"]:
        return f'<td class="sc-cell is-unmeasured" data-label="{e(arm_name)}"><span class="sc-nm">Not measured</span></td>'
    return (
        f'<td class="sc-cell is-{cell["kind"]}" data-label="{e(arm_name)}">'
        f'<span class="sc-top"><span class="sc-value">{e(cell["short"])}</span>'
        f'<span class="sc-tag">{e(cell["tag"])}</span></span>'
        f'{cell["plot"]}'
        f'<span class="sc-iv">{e(cell["short_interval"])}</span>'
        f'<span class="sr-only">{e(arm_name)}: {e(cell["text"])} difference from control, {e(cell["interval_text"])}</span></td>'
    )


def _cell_plot(cell, domain):
    def pct(v):
        return 50 + (v / domain) * 44

    oriented = cell["oriented"]
    rng = ""
    if len(oriented) == 3:
        lo, hi = sorted(oriented[1:])
        rng = f'<span class="sc-range" style="left:{pct(lo):.2f}%;width:{max(pct(hi) - pct(lo), 0.5):.2f}%"></span>'
    return (
        '<span class="sc-plot" aria-hidden="true"><span class="sc-zero"></span>'
        f'{rng}<span class="sc-dot" style="left:{pct(oriented[0]):.2f}%"></span></span>'
    )


def experiment_scorecard(metrics, treatment, heads, primary_key, caption):
    """One metric × arm matrix. Returns (table_html, unmeasured_labels, signals)."""
    e = html.escape
    rows, unmeasured, signals = [], [], []
    for metric in metrics:
        key = metric["metric"]
        label, unit = EXPERIMENT_METRICS[key]
        cells = experiment_metric_cells(metric, treatment)
        if not any(cell["measured"] for cell in cells):
            unmeasured.append(label)
            continue
        domain = max((abs(v) for cell in cells if cell["measured"] for v in cell["oriented"]), default=0) or 1
        for cell in cells:
            if cell["measured"]:
                cell["plot"] = _cell_plot(cell, domain)
        for name, cell in zip(treatment, cells):
            if cell["measured"] and cell["clear"]:
                signals.append((name, label, unit, cell))
        is_primary = key == primary_key
        any_clear = any(cell["measured"] and cell["clear"] for cell in cells)
        badge = ' <span class="sc-primary">Primary</span>' if is_primary else ""
        exploratory = ' <span class="sc-sub">exploratory</span>' if metric.get("exploratory") else ""
        unit_text = "points" if unit == "%" else unit
        rows.append(
            f'<tr class="{"is-primary" if is_primary else ""}" data-clear="{1 if any_clear or is_primary else 0}">'
            f'<th scope="row"><span class="sc-metric">{e(label)}{badge}</span>'
            f'<span class="sc-sub">{e(unit_text)}{exploratory}</span></th>'
            + "".join(_cell_html(cell, name) for name, cell in zip(treatment, cells))
            + "</tr>"
        )
    if not rows:
        return "", unmeasured, signals
    head = (
        '<th scope="col"><span class="sc-axis">Metric <span aria-hidden="true">· ← worse · better →</span></span></th>'
        + "".join(heads)
    )
    table_html = (
        f'<div class="table sc-wrap"><table class="scorecard"><caption class="sr-only">{e(caption)}</caption>'
        f'<thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )
    return table_html, unmeasured, signals


def _status_pill(state, label):
    e = html.escape
    marker = "status-stop" if state == "stopped-early" else "status-dot"
    return f'<span class="status-pill status-{e(state or "unknown")}"><span class="{marker}" aria-hidden="true"></span>{e(label)}</span>'


def render_experiments_page(data, snapshot_date, picker=None, banner="", archive_month=None, url=None, root=None):
    if picker is None:
        picker = analytics_page.picker_html(_analytics_base(root), "experiments", "experiments.json", archive_month)
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        sys.exit("experiments.json: expected schema_version 1")
    if not isinstance(data.get("experiments"), list):
        sys.exit("experiments.json: expected experiments array")
    e = html.escape
    sections, cards = [], []
    for experiment in data["experiments"]:
        if not isinstance(experiment, dict) or experiment.get("status") != "concluded":
            continue
        # Only public, sanitized narrative fields from analytics_snapshot.py are used.
        name = experiment.get("name") or "Unnamed experiment"
        question = experiment.get("hypothesis") or "Question unavailable in this snapshot."
        since, until = (experiment_stamp(experiment.get(key)) for key in ("started_at", "as_of"))
        start, end = (datetime.datetime.fromisoformat(v.replace("Z", "+00:00")) for v in (since, until))
        if start > end:
            sys.exit("experiments.json: observation window ends before it starts")
        days = round((end - start).total_seconds() / 86400)
        anchor = f"experiment-{len(sections) + 1}"
        arms = [arm for arm in experiment.get("arms", []) if isinstance(arm, dict) and isinstance(arm.get("name"), str)]
        arm_names = {arm["name"] for arm in arms}
        control_names = {arm["name"] for arm in arms if arm.get("control")} or {"control"}
        treatment_arms = [arm for arm in arms if arm["name"] not in control_names]
        treatment = [arm["name"] for arm in treatment_arms]
        control = next((arm for arm in arms if arm["name"] in control_names), None)
        enrolled = sum(arm["n"] for arm in arms if type(arm.get("n")) is int and arm["n"] >= 0)
        warning_kinds = experiment.get("warning_kinds")

        verdict = experiment.get("verdict") or {}
        state = verdict.get("state") if isinstance(verdict.get("state"), str) else None
        verdict_text = verdict.get("label") or state or "Unavailable"
        # Every published experiment is concluded; a frozen collecting verdict
        # means it stopped before the sample threshold, rather than still running.
        display_state = "stopped-early" if state == "collecting" else state
        status = STATUS_LABEL.get(display_state, (state or "Concluded").replace("_", " ").capitalize())
        status_reason = STOPPED_EARLY_REASON if display_state == "stopped-early" else ""
        if status_reason:
            verdict_text = status
        chosen = experiment.get("concluded_arm")
        has_choice = isinstance(chosen, str) and chosen in arm_names
        choice = e(chosen) if has_choice else "None recorded"
        recommended = verdict.get("arm")
        recommendation = (
            f'<p class="readout-note">Statistical recommendation: {e(recommended)}.</p>'
            if isinstance(recommended, str) and recommended in arm_names else ""
        )
        reasons = [reason for reason in verdict.get("reasons", []) if isinstance(reason, str)]

        metrics = [metric for metric in experiment.get("metrics", []) if isinstance(metric, dict) and metric.get("metric") in EXPERIMENT_METRICS]
        primary = [metric for metric in metrics if metric["metric"] == experiment.get("primary_metric")]
        primary_ids = {id(m) for m in primary}
        guardrails = [m for m in metrics if id(m) not in primary_ids and not m.get("exploratory")]
        exploratory = [m for m in metrics if id(m) not in primary_ids and m.get("exploratory")]
        primary_key = experiment.get("primary_metric")
        primary_label = EXPERIMENT_METRICS[primary_key][0] if primary_key in EXPERIMENT_METRICS else "Unavailable"

        heads = []
        fidelity = {}
        for arm in treatment_arms:
            fid = experiment_fidelity(arm, len(treatment_arms), warning_kinds)
            fidelity[arm["name"]] = fid
            tags = []
            if arm.get("retired_segment") is not None:
                tags.append("retired")
            if arm.get("drifted"):
                tags.append("drifted")
            tag_html = "".join(f' <span class="sc-flag">{t}</span>' for t in tags)
            sub = f"n={experiment_count(arm.get('n'))}"
            if fid and fid[1]:
                sub += f" · {fid[0]:,}/{fid[1]:,} on own crew"
            heads.append(
                f'<th scope="col"><span class="sc-arm">{e(arm["name"])}</span>{tag_html}'
                f'<span class="sc-sub">{e(sub)}</span></th>'
            )
        control_note = f"control n={experiment_count(control.get('n'))}" if control else "no control arm"

        decision_table, unmeasured, signals = experiment_scorecard(
            primary + guardrails, treatment, heads, primary_key,
            f"{name}: difference from control by metric and arm",
        )
        explore_table, explore_unmeasured, _ = experiment_scorecard(
            exploratory, treatment, heads, primary_key,
            f"{name}: exploratory metrics, difference from control",
        )
        better_n = sum(1 for _n, _l, _u, cell in signals if cell["kind"] == "better")
        worse_n = sum(1 for _n, _l, _u, cell in signals if cell["kind"] == "worse")

        if decision_table:
            matrix = decision_table
        else:
            empty = " ".join(
                f"{arm['name']} has {experiment_count(arm.get('n'))} enrolled tasks." for arm in treatment_arms
            )
            matrix = f'<p class="empty sc-empty">No treatment results yet. {e(empty)}</p>'
        nm_line = (
            f'<p class="sc-nm-line">Not measured for any arm: {e(", ".join(unmeasured))}.</p>'
            if unmeasured and decision_table else ""
        )
        if signals:
            items = "".join(
                f'<li class="signal is-{cell["kind"]}"><span class="signal-head"><span class="signal-arm">{e(arm)}</span>'
                f'<span class="signal-tag">{e(cell["tag"])}</span></span>'
                f'<span class="signal-metric">{e(label)}</span>'
                f'<span class="signal-value">{e(cell["short"])} <span class="unit">{e("points" if unit == "%" else unit)}</span></span>'
                f'<span class="signal-iv">{e(cell["short_interval"])}</span>'
                f'<span class="sr-only">{e(arm)}: {e(cell["text"])} difference from control, {e(cell["interval_text"])}</span></li>'
                for arm, label, unit, cell in signals
            )
            signals_html = f'<ul class="signals">{items}</ul>'
        else:
            signals_html = '<p class="empty">No decision metric has an interval that excludes zero yet.</p>'

        other_html = ""
        if exploratory:
            explore_nm = (
                f'<p class="sc-nm-line">Not measured for any arm: {e(", ".join(explore_unmeasured))}.</p>'
                if explore_unmeasured and explore_table else ""
            )
            other_html = (
                f'<details class="diff-exploratory"><summary>Other metrics ({len(exploratory)})</summary>'
                '<p class="board-note">Exploratory metrics: recorded for context, not decision metrics.</p>'
                + (explore_table or '<p class="empty">Not measured for any arm.</p>') + explore_nm + '</details>'
            )
        raw_html = (
            '<details class="experiment-raw"><summary>Raw per-arm outcomes</summary>'
            + "".join(experiment_metric_table(metric, arms) for metric in metrics) + '</details>'
        ) if metrics else ""

        arm_rows = []
        for arm in arms:
            crews = "".join(
                f'<span class="crew-chip">{e(row["crew"])} <span class="unit">{experiment_count(row.get("tasks"))}</span></span>'
                for row in arm.get("crew_mix", [])
                if isinstance(row, dict) and isinstance(row.get("crew"), str)
                and not gap_identity(row["crew"], row.get("model"))
            ) or '<span class="unit">None observed</span>'
            flags = [label for key, label in (("control", "control"), ("drifted", "drifted")) if arm.get(key)]
            if arm.get("retired_segment") is not None:
                flags.append("retired")
            flag_html = "".join(f' <span class="sc-flag">{f}</span>' for f in flags)
            if arm["name"] in control_names:
                fid_html = '<span class="unit">Reference arm</span>'
            else:
                fid = fidelity.get(arm["name"])
                if fid is None:
                    fid_html = '<span class="unit">Not recorded</span>'
                elif fid[1] == 0:
                    fid_html = '<span class="unit">No tasks yet</span>'
                else:
                    share = fid[0] / fid[1] * 100
                    fid_html = (
                        f'<span class="fid"><span class="fid-bar" aria-hidden="true"><span style="width:{share:.0f}%"></span></span>'
                        f'<span class="fid-text">{fid[0]:,} / {fid[1]:,}</span></span>'
                    )
            arm_rows.append(
                f'<tr><th scope="row"><span class="arm-name">{e(arm["name"])}</span>{flag_html}</th>'
                f'<td data-label="Enrolled">{experiment_count(arm.get("n"))}</td>'
                f'<td data-label="Ran on its own crew">{fid_html}</td>'
                f'<td data-label="Observed crews"><span class="crew-chips">{crews}</span></td></tr>'
            )
        arms_table = (
            '<div class="table"><table class="arms-table"><caption class="sr-only">Arms, enrolment and treatment delivery</caption>'
            '<thead><tr><th scope="col">Arm</th><th scope="col">Enrolled</th><th scope="col">Ran on its own crew</th>'
            '<th scope="col">Observed crews</th></tr></thead><tbody>' + "".join(arm_rows) + '</tbody></table></div>'
        )

        short = experiment_short_question(experiment, arms, metrics)
        question_html = (
            f'<p class="question-short">{e(short)}</p>'
            f'<details class="question-full"><summary>Full question and design</summary><p class="question">{e(question)}</p></details>'
            if short else f'<p class="question">{e(question)}</p>'
        )
        why_title = "Readout notes" if has_choice else "Why no decision"
        why_body = (
            "<ul>" + "".join(f"<li>{_reason_html(reason)}</li>" for reason in reasons) + "</ul>"
            if reasons else '<p class="empty">The readout records no reasons.</p>'
        )
        arm_word = "treatment arm" if len(treatment) == 1 else "treatment arms"
        day_word = "day" if days == 1 else "days"
        cards.append(
            f'<li><a class="exp-card" href="#{anchor}" data-exp="{anchor}">'
            f'<span class="exp-card-head"><span class="exp-card-name">{e(name)}</span>{_status_pill(display_state, status)}</span>'
            + (f'<span class="exp-card-reason">{e(status_reason)}</span>' if status_reason else "")
            + f'<span class="exp-card-q">{e(short or question)}</span>'
            f'<span class="exp-card-meta"><span>{len(treatment)} {arm_word}</span><span>{enrolled:,} tasks</span><span>{days} {day_word}</span></span>'
            f'<span class="exp-card-signals"><span class="is-better">{better_n} clear better</span>'
            f'<span aria-hidden="true">·</span><span class="is-worse">{worse_n} clear worse</span></span></a></li>'
        )
        sections.append(f'''<section class="board experiment" id="{anchor}" data-exp-section>
<div class="exp-head"><h2>{e(name)}</h2>{_status_pill(display_state, status)}</div>
{render_window(since, until)}
<p class="board-note">Cumulative observations from experiment start to readout ({days} {day_word}), not a rolling 30-day window.</p>
<dl class="readout">
<div><dt>Verdict</dt><dd>{e(verdict_text)}</dd></div>
<div><dt>Chosen arm</dt><dd>{choice}</dd></div>
<div><dt>Primary metric</dt><dd>{e(primary_label)}</dd></div>
<div><dt>Enrolled</dt><dd>{enrolled:,} tasks</dd></div>
</dl>
{f'<p class="readout-note">{e(status_reason)}</p>' if status_reason else ''}
{recommendation}
<div class="exp-split">
<div class="exp-question"><h3>Question</h3>{question_html}</div>
<div class="exp-why"><h3>{why_title}</h3>{why_body}</div>
</div>
<h3>Clear signals <span class="h-note">· interval excludes zero</span></h3>
{signals_html}
<div class="sc-head"><h3>Difference from control <span class="h-note">· {e(control_note)}</span></h3>
<div class="sc-tools"><ul class="sc-legend"><li><i class="k-better"></i>Better</li><li><i class="k-worse"></i>Worse</li><li><i class="k-lean"></i>Leans (interval crosses zero)</li></ul>
<button type="button" class="sc-filter" aria-pressed="false" hidden>Clear signals only</button></div></div>
{matrix}
{nm_line}
{other_html}{raw_html}
<h3>Arms and treatment delivery</h3>
{arms_table}
</section>''')
    method = '''<section class="exp-method" id="method"><details><summary>Method and caveats</summary><ul>
<li>Concluded is a lifecycle state, not proof of a winner. A verdict may be withheld or inconclusive. An experiment stopped before reaching the minimum sample has no verdict, and a chosen arm may be absent.</li>
<li>A cell is shaded only when its interval excludes zero. Every other cell is a direction, not a result. Intervals are copied from the readout; unavailable values are not zero.</li>
<li>Each cell is the treatment arm minus control. The plot runs worse to the left and better to the right, using each metric's own direction.</li>
<li>Support is specific to each metric; open regression windows can leave outcomes unsettled.</li>
<li>Windows are cumulative from experiment start to readout, not a rolling 30-day window.</li>
<li>"Ran on its own crew" counts tasks on the observed crew named like the arm; for a single treatment arm with no such crew it is enrolled tasks minus the readout's recorded crew mismatches.</li>
<li>The short question is assembled from the readout's arms, primary metric, population and guardrails; the full question is the experiment's own text.</li>
<li>These are experiment outcomes, not ranked crew scorecards. See the <a href="/notes/crew-rankings-method/">method note</a>.</li>
</ul></details></section>'''
    picker_cards = f'<nav class="exp-picker" aria-label="Choose an experiment"><ul>{"".join(cards)}</ul></nav>' if cards else ""
    body = f'''<article class="analytics experiments">
<h1>Concluded experiments</h1>
{banner}{picker}
<p class="summary">Questions, per-arm outcomes and decisions from Orbit's concluded experiments.</p>
<p class="as-of">Snapshot {e(snapshot_date)}. Built from the committed daily snapshot; no live Orbit calls.</p>
<p class="board-note">Concluded does not mean a winner. Only shaded cells have an interval that excludes zero; everything else is a direction, not a result. <a href="#method">Method and caveats</a>.</p>
{picker_cards}
{''.join(sections) if sections else '<p class="empty">No concluded experiments in this snapshot.</p>'}
{method if sections else ''}
</article>'''
    return page(
        "Concluded experiments — Constellation Works",
        "Questions, arms, aggregate outcomes, intervals and decisions from concluded Orbit experiments.",
        url or f"{SITE}/analytics/experiments/", body, current="analytics",
        extra_css=("analytics.css",), extra_js=("analytics.js",),
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
