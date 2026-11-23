# Agent instructions

This repository builds the static site for constellation-works.com. `CLAUDE.md` imports these instructions.

## Rules

- Follow [README.md#constellation-site](README.md#constellation-site) for repository scope and generated brand assets.
- Follow [README.md#notes](README.md#notes) for note approval and publication.

## Branching

- Use `main` as the integration branch; pushes to it publish through the [website workflow](.github/workflows/website.yml).

## Gates

- Before handoff, build the site with `uv run --with markdown==3.8.2 python3 build.py`.

## Code

- Follow [README.md#local-preview](README.md#local-preview) to preview the site and [README.md#deploy](README.md#deploy) for production deployment details.

## Tests

- Before handoff, run the full suite with `uv run --with markdown==3.8.2 python3 -m unittest discover -s tests -v`.
