#!/usr/bin/env python3
"""Build a weekly crew-ranking note: the frozen record of the /ranking/ crew boards.

The Ranking page keeps no history (its newest snapshot's 30 days only), so each
weekly note freezes that page's Crews by role boards for the 30 days ending on
the note's date. For a date D the window is 30 days ending D 00:00 UTC, read with
the scorecard's `--until` (ORB-23066), so a past date regenerates the same
window. The settled reviewer board is the 30 days before that.

It writes:

- data/crew-rankings/<date>/scorecards.json: the frozen input, projected exactly
  as scripts/analytics_snapshot.py projects the Ranking page's scorecards.json
  (gap rows dropped, crew, model and recorded effort per row), so the note's
  Crews by role section is drawn by the page's own renderer
  (build.render_crews_by_role) from this directory;
- data/crew-rankings/<date>/facts.json: the window, the MVP and the writer;
- notes/crew-rankings-<date>/: a draft index.md and the CSVs it publishes
  (all-tiers.csv, by-tier.csv, reviewers.csv, pilots.csv).

The MVP is the rank-1 row of the all-tiers implementer board, nothing else: a
row is one crew, model and recorded effort. The MVP line, summary and byline
name it with the boards' own crew@effort label (build.crew_label, ``(est.)``
when the effort is the crew's configured estimate) and its model; the title and
``--writer-only`` use the plain crew. The MVP crew writes the note: it replaces the victory-address
placeholder with two to four first-person sentences. build.py refuses to
publish a note while the placeholder remains.

Usage, on the Orbit owner host:

    python3 scripts/crew_rankings.py [<date>] [--workspace orbit]
        # <date> is YYYY-MM-DD, default today (UTC)
    python3 scripts/crew_rankings.py <date> --from data/crew-rankings/<date>
        # regenerate from the frozen scorecards.json, without calling orbit
    python3 scripts/crew_rankings.py <date> --writer-only [--crews a,b,...]
        # print only the writer JSON (the MVP's crew); write no files

--force overwrites an existing note's index.md (the writer's address is lost).
"""

import argparse
import csv
import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import analytics_snapshot as snap  # noqa: E402  (shared scorecard projection)

WINDOW = "30d"
PLACEHOLDER = "{{victory-address}}"
METHOD = "../crew-rankings-method/"
TAGS = "operating data, crew selection, rankings, weekly"


def day_start(day):
    return f"{day.isoformat()}T00:00:00Z"


def fetch(workspace, until, settled_until):
    """The 30d scorecards ending `until`, projected like the Ranking page's snapshot."""
    def card(role, *flags, end=until):
        return snap.orbit_json(["agents", "scorecard", "--role", role, "--window", WINDOW,
                                "--until", end, *flags], workspace)

    cards = {
        "implementers": card("implementers"),
        "implementers_by_type": card("implementers", "--by-type"),
        "reviewers": card("reviewers"),
        "reviewers_settled": card("reviewers", end=settled_until),
        "pilots": card("pilots"),
    }
    estimates = snap.crew_effort_estimates(snap.crews_needing_estimates(cards), workspace)
    scorecards = snap.assemble_scorecards(cards, True, snap.empty_dropped(), estimates)
    snap.scan(scorecards, snap.forbidden_patterns(snap.host_names()))
    snap.assert_no_gap_values(scorecards)
    snap.assert_unique_rows(scorecards)
    return scorecards


def effort_of(row):
    """A row's raw effort identity (recorded effort or label), or None."""
    return row.get("reasoning_effort") or row.get("effort_label") or None


def board_label(row):
    """The MVP's name as the boards show it: ``haiku@xhigh (est.)``, ``opus@medium``.

    Taken from build.py's own crew_label/crew_view, the function that names
    every crew row on the boards, so the MVP line, summary and byline never
    disagree with the tables. Imported here, not at module load, so
    ``--writer-only`` keeps working without build.py's ``markdown`` dependency.
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import build  # noqa: E402  (the site build: the boards' label function)
    return build.crew_label({"crew": row["crew"], **build.crew_view(row)})


def ranked(board):
    rows = [r for r in board.get("rows") or [] if r.get("rank") is not None and r.get("score") is not None]
    return sorted(rows, key=lambda r: (r["rank"], -r["score"], r["crew"], r["model"], effort_of(r) or ""))


def mvp_row(scorecards):
    """The rank-1 row of the all-tiers implementer board, or None when nothing is ranked."""
    rows = ranked(scorecards["implementers"])
    return rows[0] if rows else None


def writer(mvp, crews, fallback):
    """The crew that writes the note: the MVP's crew (``--writer-only``)."""
    crew = mvp["crew"] if mvp else None
    if crew and crews is not None and crew not in crews and crew.split("@", 1)[0] in crews:
        crew = crew.split("@", 1)[0]  # a crew named for its effort routes to its plain crew
    ok = crew is not None and (crews is None or crew in crews)
    return {
        "crew": crew if ok else fallback,
        "source": "mvp" if ok else "fallback",
        "mvp_crew": mvp["crew"] if mvp else None,
        "model": mvp["model"] if mvp else None,
        "effort": effort_of(mvp) if mvp else None,
        "effort_estimate": mvp.get("effort_estimate") if mvp else None,
        "score": round(mvp["score"], 1) if mvp else None,
        "units": mvp["units"] if mvp else None,
    }


def effort_cells(row):
    return {"effort": row.get("reasoning_effort") or row.get("effort_label") or "",
            "effort_estimate": row.get("effort_estimate") or ""}


def board_rows(card, **extra):
    out = []
    for r in card.get("rows") or []:
        counts = r.get("counts") or {}
        landed = counts.get("weighted_landed")
        out.append({
            **extra,
            "rank": r["rank"] if r.get("rank") is not None else "",
            "crew": r["crew"], "model": r["model"], **effort_cells(r),
            "units": r["units"],
            "score": round(r["score"], 1) if r.get("score") is not None else "",
            "fleet_average": card.get("fleet_average"),
            **({"landed_pct": round(landed / r["units"] * 100, 1) if landed is not None and r["units"] else ""}
               if card.get("role") == "implementers" else {}),
        })
    return out


def tier_rows(block):
    return [{
        "tier": c["tier"], "type": c["type"], "rank": c["rank"] if c.get("rank") is not None else "",
        "crew": c["crew"], "model": c["model"], **effort_cells(c), "tasks": c["n"],
        "score": round(c["score"], 1) if c.get("score") is not None else "",
        "crew_mean": round(c["crew_mean"], 1) if c.get("crew_mean") is not None else "",
    } for c in block.get("cells") or []]


def write_csv(path, rows):
    if not rows:
        path.unlink(missing_ok=True)
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def score_text(value):
    return f"{value:.1f}"


def note_text(day, scorecards, mvp, data_rel):
    impl = scorecards["implementers"]
    since, until = impl["window"]["since"], impl["window"]["until"]
    crew = mvp["crew"] if mvp else "none"
    if mvp:
        label, model = board_label(mvp), mvp["model"]
        score = score_text(mvp["score"])
        mvp_line = f"**MVP: {label}, {model}, {score}** on {mvp['units']:,} {impl['unit']}."
        byline = f"{label} ({model}), MVP of the week, {score}"
        summary = (f"The crew boards for the 30 days ending {day.isoformat()}: implementers, reviewers and "
                   f"pilots. MVP: {label}, {model}, {score}.")
    else:
        mvp_line = "**No MVP this week:** no implementer crew reached the board's minimum support."
        byline = "Constellation Works"
        summary = f"The crew boards for the 30 days ending {day.isoformat()}: implementers, reviewers and pilots."
    intro = (
        f"This is the weekly crew ranking for the 30 days from {since} to {until} (UTC), a frozen copy "
        "of the crew boards on the [Ranking page](/ranking/), which shows only the latest 30 days. "
        f"Each crew is scored in its role against the fleet's own rate, and [how the crew rankings work]({METHOD}) "
        "explains the scores. The MVP is the rank-1 crew of the all-tiers implementer board."
    )
    address = (f"{PLACEHOLDER} {crew} replaces this line with a victory address: two to four short "
               "first-person sentences, every number taken from this note's CSVs, no em dashes, "
               "and nothing that restates or reframes the boards.")
    limits = ("Limits: these are 30 days of one repository's managed tasks, not a controlled comparison; "
              "reviewer scores stay provisional until their findings settle; and implementer, reviewer "
              "and pilot scores are on different scales.")
    return f"""---
title: [Crew Ranking - {day.isoformat()}]: MVP {crew}
summary: {summary}
status: draft
date: {day.isoformat()}
author: {byline}
tags: {TAGS}
---

{intro}

{mvp_line}

## Victory address

{address}

## Crews by role

<!-- crews-by-role: {data_rel} -->

{limits}
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("date", nargs="?", help="the note's date, YYYY-MM-DD (default today, UTC)")
    ap.add_argument("--workspace", default="orbit")
    ap.add_argument("--from", dest="source", help="read a frozen data/crew-rankings/<date>/ instead of orbit")
    ap.add_argument("--notes-dir", default=str(ROOT / "notes"))
    ap.add_argument("--data-dir", default=str(ROOT / "data" / "crew-rankings"))
    ap.add_argument("--fallback-crew", default="opus",
                    help="crew that writes the note when no implementer crew is ranked (default opus)")
    ap.add_argument("--crews", help="comma list of crews configured in the workspace; "
                    "an MVP crew outside it hands the note to --fallback-crew")
    ap.add_argument("--writer-only", action="store_true",
                    help="print only the writer JSON on stdout and write no files")
    ap.add_argument("--force", action="store_true", help="overwrite an existing note's index.md")
    a = ap.parse_args()
    try:
        day = (datetime.date.fromisoformat(a.date) if a.date
               else datetime.datetime.now(datetime.timezone.utc).date())
    except ValueError:
        ap.error(f"date must be YYYY-MM-DD, got {a.date!r}")
    crews = {c.strip() for c in a.crews.split(",") if c.strip()} if a.crews else None

    if a.source:
        scorecards = json.loads((pathlib.Path(a.source) / "scorecards.json").read_text(encoding="utf-8"))
    else:
        scorecards = fetch(a.workspace, day_start(day), day_start(day - datetime.timedelta(days=30)))
    mvp = mvp_row(scorecards)
    who = writer(mvp, crews, a.fallback_crew)
    if a.writer_only:
        print(json.dumps(who))
        return

    data = pathlib.Path(a.data_dir) / day.isoformat()
    note = pathlib.Path(a.notes_dir) / f"crew-rankings-{day.isoformat()}"
    index = note / "index.md"
    if index.exists() and not a.force:
        sys.exit(f"{index} exists; pass --force to overwrite it")
    data.mkdir(parents=True, exist_ok=True)
    note.mkdir(parents=True, exist_ok=True)
    (data / "scorecards.json").write_text(json.dumps(scorecards, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    impl, rev = scorecards["implementers"], scorecards["reviewers"]
    facts = {
        "date": day.isoformat(),
        "window": impl["window"],
        "windows": {"implementers": impl["window"], "implementers_by_tier": scorecards["implementers_by_tier"]["window"],
                    "reviewers_provisional": rev["provisional"]["window"],
                    "reviewers_settled": (rev.get("settled") or {}).get("window"),
                    "pilots": scorecards["pilots"]["window"]},
        "mvp": {"crew": mvp["crew"], "label": board_label(mvp), "model": mvp["model"], "effort": effort_of(mvp),
                "effort_estimate": mvp.get("effort_estimate"),
                "score": mvp["score"], "units": mvp["units"], "rank": mvp["rank"]} if mvp else None,
        "writer": who,
    }
    (data / "facts.json").write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")

    write_csv(note / "all-tiers.csv", board_rows(impl))
    write_csv(note / "by-tier.csv", tier_rows(scorecards["implementers_by_tier"]))
    write_csv(note / "reviewers.csv",
              board_rows(rev["provisional"], board="provisional")
              + (board_rows(rev["settled"], board="settled") if rev.get("settled") else []))
    write_csv(note / "pilots.csv", board_rows(scorecards["pilots"]))
    try:
        data_rel = data.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        data_rel = data.as_posix()
    index.write_text(note_text(day, scorecards, mvp, data_rel), encoding="utf-8")
    print(f"wrote {index} (draft) and {data}; MVP {board_label(mvp) if mvp else 'none'}; writer {who['crew']}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
