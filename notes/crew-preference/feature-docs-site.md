# Versioned documentation site

Build the documentation site for a command-line tool that ships a new minor
release roughly every month. Users run old versions for a long time, so the
site must show the docs for the version they have, and make it obvious when
they are reading docs for a different one.

The first users are the tool's users: developers who arrive from a search
engine or from a link printed by the CLI, often on a phone, and maintainers
who write the docs in Markdown next to the code. It does not host a forum,
a blog or a changelog beyond the release notes already in the repository.

**Acceptance demo:** push a release tag and see the site rebuild with a new
version while old versions stay browsable; open a CLI reference page from a
link the CLI printed and land on the right version and anchor; search for a
flag that was renamed between versions and find both, clearly labelled; break
a link in a draft and see the preview build fail with the exact file and line;
navigate the whole site with a keyboard and a screen reader.

## Foundation

This checkout holds the site generator and theme. The docs source lives in the
tool's repository under `docs/` at each release tag. The CLI can describe its
own commands and flags as JSON; that format is documented in
`docs/help-json.md` here and is the only supported way to generate reference
pages.

Build a static site. No server-side rendering at request time.

## Required user workflow

1. A maintainer writes a guide in Markdown, runs a local preview with live
   reload, and sees exactly what production will show.
2. A pull request builds a preview deployment and posts its URL; link
   checking, spelling of CLI flags against the reference, and accessibility
   checks run and block merge on failure.
3. A release tag builds that version's docs from its own `docs/` tree and
   its own help JSON, and adds it to the version switcher.
4. A reader lands on any page, sees which version it documents, switches
   version and stays on the equivalent page when one exists, or gets a
   helpful fallback when it does not.
5. A reader searches across the current version, or all versions, with
   results that show the version and section and highlight the match.
6. Every CLI command and flag has a stable URL that the CLI can print in
   error messages.

## Semantic contract

### Versions

- `latest` always means the newest stable release. Prereleases are
  published under their own version and never become `latest`.
- Old versions are rebuilt only when the theme or generator changes, and
  a rebuild must not change their content.
- Pages carry a canonical URL so search engines prefer the latest version;
  old versions are indexed but ranked below it.
- A page that was removed or renamed in a later version redirects or links
  to its successor when a mapping exists, and says so.

### Reference pages

- Generated only from help JSON. Hand-written text may be added through
  named include files but may not change generated signatures.
- Deprecated and renamed flags stay listed with their replacement and the
  version that changed them.
- Anchors are derived from command and flag names and are stable across
  versions.

### Search

- Runs in the browser from a prebuilt index; no search service.
- Index size per version stays within a declared budget; large versions
  load their index lazily.
- Code blocks and flags are searchable as exact tokens, including leading
  dashes.

## Engineering boundaries

The generator is a Python package (`generator/`). The theme is plain HTML,
CSS and minimal JavaScript (`theme/`); the site must be readable with
JavaScript disabled, with only search and the version switcher degrading.
Hosting is any static host behind a CDN; the build produces a directory.

Meet WCAG 2.2 AA. Support light and dark themes and print. No tracking or
third-party scripts.

## Milestones

| Milestone | Reviewable result |
|---|---|
| 1. Content model | Page, version and navigation model, help JSON importer, URL and anchor scheme, a theme sketch. |
| 2. Single version | Markdown guides and generated reference for one version, local preview with live reload. |
| 3. Many versions | Tag-driven builds, version switcher with page mapping, redirects, canonical URLs, prerelease handling. |
| 4. Search and quality gates | Browser search with lazy indexes, link checker, flag-spelling check, accessibility checks, PR previews. |
| 5. Polish and handoff | Mobile, print and dark theme, performance budget, maintainer guide, migration of existing docs. |

Settle the URL and anchor scheme before reference and search work split.

## Validation

- Fixture repository with six tags covering a renamed command, a removed
  flag, a prerelease, a guide moved between sections and a malformed help
  JSON file.
- Golden-output tests for generated reference pages.
- Automated accessibility checks on every page template and a manual
  screen-reader pass on the demo path.
- A performance budget for first load on a mid-range phone on a slow
  connection, measured in CI.

The product is complete when the acceptance demo passes on the fixture
repository and on the tool's real history. No public launch in v1.
