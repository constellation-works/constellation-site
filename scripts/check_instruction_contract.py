#!/usr/bin/env python3
"""Check provider instruction files, their byte budgets, and their paths."""

from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")
PATH_TOKEN = re.compile(
    r"(?<![\w.-])(?:\.{1,2}/)?(?:[\w.-]+/)*[\w.-]+\.(?:md|py|yml|yaml|toml|sh|json)(?![\w.-])"
)
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
CODE = re.compile(r"`([^`]+)`")


def fail(path: Path, message: str) -> None:
    print(f"{path.relative_to(ROOT)}: {message}", file=sys.stderr)


def instruction_directories() -> list[Path]:
    found = []
    for current, dirs, files in os.walk(ROOT):
        dirs[:] = [name for name in dirs if name not in {".git", ".orbit", "node_modules", "target", ".venv"}]
        if set(files).intersection(NAMES):
            found.append(Path(current))
    return found


def check_provider_files(directory: Path) -> bool:
    ok = True
    agents = directory / "AGENTS.md"
    if not agents.exists() or agents.is_symlink() or not agents.is_file():
        fail(agents, "must be a regular source file in every instruction directory")
        return False
    for name in NAMES[1:]:
        provider = directory / name
        if not provider.exists() and not provider.is_symlink():
            continue
        if provider.is_symlink():
            try:
                valid = provider.resolve(strict=True) == agents.resolve(strict=True)
            except OSError:
                valid = False
            if not valid:
                fail(provider, "must resolve to the adjacent AGENTS.md")
                ok = False
        else:
            try:
                first_line = provider.read_text(encoding="utf-8").splitlines()[0]
            except (OSError, IndexError, UnicodeError):
                first_line = ""
            if first_line != "@AGENTS.md":
                fail(provider, "must be a symlink to AGENTS.md or start with @AGENTS.md")
                ok = False
    budget = 8000 if directory == ROOT else 4000
    size = sum((directory / name).stat().st_size for name in NAMES if (directory / name).exists())
    if size > budget:
        fail(agents, f"instruction stack is {size} bytes; limit is {budget}")
        ok = False
    return ok


def heading_slugs(markdown: str) -> set[str]:
    slugs = set()
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", markdown, re.M):
        slug = re.sub(r"[`*_]", "", heading).lower()
        slug = re.sub(r"[^\w\- ]", "", slug)
        slugs.add(re.sub(r"\s+", "-", slug.strip()))
    return slugs


def check_path(source: Path, target: str) -> bool:
    target = target.strip()
    if not target or target.startswith(("https://", "http://", "mailto:", "tel:")):
        return True
    raw_path, separator, anchor = target.partition("#")
    path = (source.parent / raw_path).resolve() if raw_path else source.resolve()
    try:
        path.relative_to(ROOT)
    except ValueError:
        fail(source, f"path escapes the repository: {target}")
        return False
    if not path.exists():
        fail(source, f"path does not resolve: {target}")
        return False
    if separator and anchor and path.is_file() and path.suffix.lower() in {".md", ".markdown"}:
        try:
            slugs = heading_slugs(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            fail(source, f"cannot read linked Markdown file: {target}")
            return False
        if anchor not in slugs:
            fail(source, f"heading does not resolve: {target}")
            return False
    return True


def check_document(source: Path) -> bool:
    ok = True
    text = source.read_text(encoding="utf-8")
    for target in LINK.findall(text):
        ok = check_path(source, target) and ok
    for span in CODE.findall(text):
        try:
            tokens = shlex.split(span)
        except ValueError:
            tokens = span.split()
        candidates = PATH_TOKEN.findall(span)
        for index, token in enumerate(tokens[:-1]):
            if token in {"-s", "--start-directory"}:
                candidates.append(tokens[index + 1])
        for candidate in dict.fromkeys(candidates):
            ok = check_path(source, candidate) and ok
    return ok


def main() -> int:
    directories = instruction_directories()
    if not directories:
        print("No instruction files found.")
        return 0
    ok = True
    for directory in directories:
        ok = check_provider_files(directory) and ok
        agents = directory / "AGENTS.md"
        if agents.is_file():
            ok = check_document(agents) and ok
        for name in NAMES[1:]:
            provider = directory / name
            if provider.exists() and not provider.is_symlink():
                ok = check_document(provider) and ok
    if ok:
        print(f"Instruction contract passes for {len(directories)} director{'y' if len(directories) == 1 else 'ies'}.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
