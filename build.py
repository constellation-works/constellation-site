#!/usr/bin/env python3
"""Build the Notes section into public/notes/.

Each note is a directory under notes/ holding index.md (front matter plus Markdown)
and any files the note links to (data, images). Output is a page per note, a
/notes/ index and an Atom feed. public/notes/ is generated: do not edit or commit it.

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
import html
import pathlib
import re
import shutil
import sys

import markdown

ROOT = pathlib.Path(__file__).parent
SRC = ROOT / "notes"
OUT = ROOT / "public" / "notes"
SITE = "https://constellation-works.com"

FIELDS = {"title", "summary", "status", "date", "updated", "image", "author", "tags"}


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
      <a class="nav-orbit" href="https://orbit-cli.com">Orbit</a>
      <a href="https://github.com/constellation-works">GitHub</a>
      <button class="theme" type="button" aria-label="Switch to light theme" hidden>
        <svg class="sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>
        <svg class="moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>
      </button>
    </nav>
  </div>
</header>"""

FOOTER = """<footer>
  <div class="wrap">
    <span>&copy; 2026 Constellation Works</span>
    <span class="sp">
      <a href="/notes/feed.xml">Atom feed</a>
      <a href="https://github.com/constellation-works">github.com/constellation-works</a>
    </span>
  </div>
</footer>
<script src="/assets/theme.js"></script>"""


def page(title, description, url, body, image=None, draft=False, kind="website"):
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
<link rel="stylesheet" href="/assets/notes.css">
<script src="/assets/theme-init.js"></script>
</head>
<body>
{HEADER}
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
    body = f"""<article class="note">
{rail(note, data)}
<h1>{e(note['title'])}</h1>
{meta_block(note)}
<p class="summary">{e(note['summary'])}</p>
{render_body(note['body'])}
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


if __name__ == "__main__":
    main()
