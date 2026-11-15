"""Shared page shell and small helpers for the site build (split from build.py)."""

import hashlib
import html
import pathlib
import re
import sys
import analytics_page


ROOT = pathlib.Path(__file__).parent

SITE = "https://constellation-works.com"

def asset(name):
    """URL of a file in public/assets/ with a content hash, so a changed file is
    fetched again instead of served from a browser cache (the host caches for hours)."""
    digest = hashlib.sha256((ROOT / "public" / "assets" / name).read_bytes()).hexdigest()
    return f"/assets/{name}?v={digest[:10]}"

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

DATE_DIR = re.compile(r"\d{4}-\d{2}-\d{2}")

GAP_CREWS = {"crew unknown", "crew unavailable", "unknown"}

RANK_NON_CREW = "system"

GAP_MODELS = {"model unknown"}

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

def _analytics_base(root=None):
    return (pathlib.Path(root) if root is not None else ROOT) / "data" / "analytics"

UTC_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z")
