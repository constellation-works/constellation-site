"""Notes build (split from build.py)."""

import datetime
import html
import re
import shutil
import sys
import analytics_page
import markdown
from build_common import ROOT, SITE, page


SRC = ROOT / "notes"

OUT = ROOT / "public" / "notes"

FIELDS = {"title", "summary", "status", "date", "updated", "image", "author", "tags"}

MVP_BYLINE = re.compile(r"[^,()]+(?: \(est\.\))? \([^()]+\), MVP of the week, [^,]+")

FALLBACK_BYLINE = re.compile(r"[^,()]+ \(fallback writer\), no MVP this week")

WEEKLY_SLUG = re.compile(r"crew-rankings-\d{4}-\d{2}-\d{2}")

WEEKLY_TITLE = re.compile(r"\[Crew Ranking - \d{4}-\d{2}-\d{2}\]: (?:MVP|co-MVPs|no MVP)\b.*")

VICTORY_PLACEHOLDER = "{{victory-address}}"

CREWS_EMBED = re.compile(r"<!-- crews-by-role: (\S+) -->")

CREWS_DATA = re.compile(r"data/crew-rankings/\d{4}-\d{2}-\d{2}")

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
    weekly_byline = bool(MVP_BYLINE.fullmatch(author) or FALLBACK_BYLINE.fullmatch(author))
    meta["authors"] = (
        [author] if weekly_byline
        else [a.strip() for a in author.split(",") if a.strip()]
    ) or ["Constellation Works"]
    if WEEKLY_SLUG.fullmatch(path.parent.name):
        if not WEEKLY_TITLE.fullmatch(meta["title"]):
            sys.exit(f"{path}: a weekly crew-ranking title names its MVP, co-MVPs or no MVP, got {meta['title']!r}")
        if not weekly_byline:
            sys.exit(f"{path}: a weekly crew-ranking author is `<crew> (<model>), MVP of the week, <score>` "
                     f"or `<crew> (fallback writer), no MVP this week`, got {author!r}")
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
    component's stylesheets in analytics_page.ANALYTICS_CSS and analytics.js).
    """
    from build_ranking import render_crews_by_role
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
             extra_css=analytics_page.ANALYTICS_CSS if embedded else (),
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
