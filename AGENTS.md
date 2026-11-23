# constellation-site

This repository builds the static site for [constellation-works.com](https://constellation-works.com), served by Cloudflare Pages. Agent providers share these instructions through the root `CLAUDE.md`, which imports this file.

## Rules

- For the marketing approval and note publication rules, follow [README: Notes](README.md#notes).

## Branching

- Use `main` as the integration branch; the [Website workflow](.github/workflows/website.yml) deploys pushes to it.

## Gates

- Before handoff, run `uv run --with markdown==3.8.2 python3 build.py`; the Website workflow runs this build for pull requests and production deploys.
- Before handoff, run `python3 scripts/check_instruction_contract.py`; CI runs it on pull requests and pushes to `main`.

## Code

- For brand asset sources and regeneration, follow [README: project overview](README.md#constellation-site).

## Tests

- Before handoff, run `uv run --with markdown==3.8.2 python3 -m unittest discover -s tests -v`.

## Site

- For local preview commands, follow [README: Local preview](README.md#local-preview).
