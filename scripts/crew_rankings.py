#!/usr/bin/env python3
"""Build a weekly crew-ranking note: the frozen record of the /ranking/ crew boards and its MVP.

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
- data/crew-rankings/<date>/rank.json: the settled model rank for the note's date,
  projected as the analytics snapshot projects rank.json. The MVP is read from it;
- data/crew-rankings/<date>/facts.json: the windows, the MVP band and the writer;
- notes/crew-rankings-<date>/: a draft index.md and the CSVs it publishes
  (all-tiers.csv, by-tier.csv, reviewers.csv, pilots.csv).

The MVP is the top tie band of the settled model rank, never the live board: the
models whose rank is the lowest in the board (``1=`` when shared). A shared band
gives co-MVPs. The rank is read with ``orbit agents rank --until <D>``, so its
ranked window ends at the settle lag (14 days) before the note's date. Only a
qualified board whose noise scales are a calibrated season (``scales_source``
``season``) names an MVP. Otherwise the note names none, says why, and the
fallback crew writes it.

The band's first model, in Orbit's own band order (cheapest first), writes the
victory address, through its crew with the most implemented tasks in the window.
The crew boards stay in the note for the record and earn nothing. build.py
refuses to publish a note while the placeholder remains.

Usage, on the Orbit owner host:

    python3 scripts/crew_rankings.py [<date>] [--workspace orbit]
        # <date> is YYYY-MM-DD, default today (UTC)
    python3 scripts/crew_rankings.py <date> --from data/crew-rankings/<date>
        # regenerate from the frozen scorecards.json and rank.json, without calling orbit
    python3 scripts/crew_rankings.py <date> --writer-only [--crews a,b,...]
        # print only the writer JSON (the MVP band's writer); write no files

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
import analytics_snapshot as snap  # noqa: E402  (shared scorecard and rank projection)

WINDOW = "30d"
PLACEHOLDER = "{{victory-address}}"
METHOD = "../crew-rankings-method/"
TAGS = "operating data, crew selection, rankings, weekly"
RULE = ("the MVP is the top tie band of the settled model rank for the note's date; "
        "a shared band gives co-MVPs, and the band's first model in Orbit's order writes the address")


def day_start(day):
    return f"{day.isoformat()}T00:00:00Z"


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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
    scorecards = snap.assemble_scorecards(cards, True, snap.empty_dropped())
    snap.scan(scorecards, snap.forbidden_patterns(snap.host_names()))
    snap.assert_no_gap_values(scorecards)
    snap.assert_unique_rows(scorecards)
    return scorecards


def fetch_rank(workspace, until):
    """The settled 30d model rank ending at the settle lag before `until`, projected like the snapshot's rank.json.

    Not a live board: the request has no live flag, and the projection refuses a provisional board, so the MVP never comes from one.
    """
    patterns = snap.forbidden_patterns(snap.host_names())
    payload = snap.orbit_json(["agents", "rank", "--window", WINDOW, "--until", until], workspace)
    rank = snap.project_rank(payload, snap.empty_dropped(), patterns, [0])
    snap.scan(rank, patterns)
    return rank


def mvp_band(rank):
    """(band, why): the MVP's top band in Orbit's band order, or ([], why) when no board names one.

    The band is the rows with the lowest rank among eligible, scored rows. Rows keep the
    order the rank board gave them, so a shared band is listed cheapest first.
    """
    if rank is None:
        return [], "the note froze no settled model rank for its date"
    if rank.get("qualified") is not True:
        return [], "the model board has not qualified"
    scales = rank.get("scales_source")
    if scales == "window_estimate":
        return [], "the noise scales are estimated from this window, not frozen for a calibrated season"
    if scales != "season":
        return [], "no calibrated season's noise scales are in force"
    ranked = [
        row for row in rank.get("rows") or []
        if row.get("eligible") is True and isinstance(row.get("rank"), int)
        and not isinstance(row.get("rank"), bool) and number(row.get("score"))
    ]
    if not ranked:
        return [], "no model is ranked"
    top = min(row["rank"] for row in ranked)
    return [row for row in ranked if row["rank"] == top], None


def crew_key_label(key):
    """A rank crew key as the boards name it: ``crew@effort``, or ``crew · effort unknown`` when no effort was recorded."""
    return key if "@" in key else f"{key} · effort unknown"


def choose_writer(band, crews, fallback):
    """The writer of a band: the first model's crew with the most implemented tasks (``--writer-only``).

    A crew named for its effort routes to its plain crew when only that is configured. When the
    writing crew is not configured, the fallback writes the note.
    """
    model = band[0]
    crew_rows = model.get("crews") or []
    key = max(crew_rows, key=lambda entry: entry.get("tasks") or 0)["crew"] if crew_rows else None
    name = key
    if name and crews is not None and name not in crews and name.split("@", 1)[0] in crews:
        name = name.split("@", 1)[0]
    ok = name is not None and (crews is None or name in crews)
    return {
        "crew": name if ok else fallback,
        "source": "mvp" if ok else "fallback",
        "mvp_crew": key,
        "model": model["model"],
        "effort": key.split("@", 1)[1] if key and "@" in key else None,
        "score": round(model["score"], 1),
        "units": model["units"],
    }


def no_writer(fallback):
    return {"crew": fallback, "source": "fallback", "mvp_crew": None, "model": None,
            "effort": None, "score": None, "units": None}


def effort_cells(row):
    return {"effort": row.get("reasoning_effort") or row.get("effort_label") or ""}


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


def names(items):
    """``a``, ``a and b``, ``a, b and c``."""
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def interval_text(row):
    interval = row.get("interval")
    if isinstance(interval, dict) and number(interval.get("p10")) and number(interval.get("p90")):
        return f"p10–p90 {score_text(interval['p10'])}–{score_text(interval['p90'])}"
    return "interval not published"


def band_phrase(row):
    """One band member as the note quotes it: model, score and interval from the frozen rank."""
    return f"{row['model']} at {score_text(row['score'])} ({interval_text(row)})"


def title_text(day, band):
    if not band:
        return f"[Crew Ranking - {day.isoformat()}]: no MVP"
    if len(band) == 1:
        return f"[Crew Ranking - {day.isoformat()}]: MVP {band[0]['model']}"
    return f"[Crew Ranking - {day.isoformat()}]: co-MVPs {names(row['model'] for row in band)}"


def byline_text(who, band):
    """The byline names the writer: its crew label, its model, and the MVP's score it writes under."""
    if who["source"] == "mvp":
        return f"{crew_key_label(who['mvp_crew'])} ({who['model']}), MVP of the week, {score_text(who['score'])}"
    if band:
        return f"{who['crew']} (fallback writer), MVP of the week, {score_text(band[0]['score'])}"
    return f"{who['crew']} (fallback writer), no MVP this week"


def rule_text(band, who, why, fallback):
    """The paragraph that says who writes the address and the rule that picked the writer."""
    if not band:
        return f"No MVP is named this week, so the configured fallback crew, {fallback}, writes this note's victory address."
    first = band[0]
    crew_rows = first.get("crews") or []
    tasks = max((entry.get("tasks") or 0 for entry in crew_rows), default=0)
    if who["source"] != "mvp" and who["mvp_crew"] is None:
        return (f"The MVP is {first['model']}, but no crew is recorded for it, so the fallback crew, {fallback}, "
                "writes this note's victory address.")
    if who["source"] != "mvp":
        return (f"The MVP is {first['model']}, but its crew {crew_key_label(who['mvp_crew'])} is not configured "
                f"here, so the fallback crew, {fallback}, writes this note's victory address.")
    if len(band) == 1:
        return (f"{first['model']} is the only model in the top band, so its crew {crew_key_label(who['mvp_crew'])} "
                f"writes the address: the crew with the most implemented tasks in the window ({tasks:,}).")
    return (f"The top band is shared, so it is published as co-MVPs. Orbit lists a band cheapest first, so its "
            f"first model, {first['model']}, writes the address, through its crew {crew_key_label(who['mvp_crew'])}: "
            f"the crew with the most implemented tasks in the window ({tasks:,}).")


def mvp_line(band, why):
    if not band:
        return f"**No MVP this week:** {why}."
    if len(band) == 1:
        row = band[0]
        return (f"**MVP: {row['model']}, rank {row.get('rank_label') or row['rank']}, {score_text(row['score'])} "
                f"({interval_text(row)})** on {row['units']:,} implemented tasks.")
    return (f"**Co-MVPs, rank {band[0].get('rank_label') or band[0]['rank']}: "
            + "; ".join(band_phrase(row) for row in band) + ".**")


def note_text(day, scorecards, band, why, who, data_rel, fallback):
    impl = scorecards["implementers"]
    since, until = impl["window"]["since"], impl["window"]["until"]
    if band:
        head = "MVP" if len(band) == 1 else "Co-MVPs"
        summary = (f"The crew boards for the 30 days ending {day.isoformat()}: implementers, reviewers and pilots. "
                   f"{head}: " + "; ".join(band_phrase(row) for row in band) + ".")
    else:
        summary = (f"The crew boards for the 30 days ending {day.isoformat()}: implementers, reviewers and pilots. "
                   f"No MVP: {why}.")
    intro = (
        f"This is the weekly crew ranking for the 30 days from {since} to {until} (UTC), a frozen copy "
        "of the crew boards on the [Ranking page](/ranking/), which shows only the latest 30 days. "
        f"Each crew is scored in its role against the fleet's own rate, and [how the crew rankings work]({METHOD}) "
        "explains the scores. The MVP comes from the settled model rank for the note's date, frozen beside the "
        "boards in rank.json. The crew boards are shown for the record and earn nothing toward it."
    )
    address = (f"{PLACEHOLDER} {who['crew']} replaces this line with a victory address: two to four short "
               "first-person sentences, every number taken from this note's CSVs and its frozen rank.json, "
               "no em dashes, and nothing that restates or reframes the boards.")
    signature = band[0]["model"] if band else who["crew"]
    limits = ("Limits: these are 30 days of one repository's managed tasks, not a controlled comparison; "
              "reviewer scores stay provisional until their findings settle; and implementer, reviewer "
              "and pilot scores are on different scales.")
    return f"""---
title: {title_text(day, band)}
summary: {summary}
status: draft
date: {day.isoformat()}
author: {byline_text(who, band)}
tags: {TAGS}
---

{intro}

{mvp_line(band, why)}

## Victory address

{rule_text(band, who, why, fallback)}

> {address}
>
> — {signature}

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
                    help="crew that writes the note when no MVP is named, or the MVP's crew is not configured (default opus)")
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
        source = pathlib.Path(a.source)
        scorecards = json.loads((source / "scorecards.json").read_text(encoding="utf-8"))
        rank_file = source / "rank.json"
        rank = json.loads(rank_file.read_text(encoding="utf-8")) if rank_file.is_file() else None
    else:
        scorecards = fetch(a.workspace, day_start(day), day_start(day - datetime.timedelta(days=30)))
        rank = fetch_rank(a.workspace, day_start(day))
    band, why = mvp_band(rank)
    who = choose_writer(band, crews, a.fallback_crew) if band else no_writer(a.fallback_crew)
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
    if rank is not None:
        (data / "rank.json").write_text(json.dumps(rank, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    impl, rev = scorecards["implementers"], scorecards["reviewers"]
    facts = {
        "date": day.isoformat(),
        "window": impl["window"],
        "windows": {"implementers": impl["window"], "implementers_by_tier": scorecards["implementers_by_tier"]["window"],
                    "reviewers_provisional": rev["provisional"]["window"],
                    "reviewers_settled": (rev.get("settled") or {}).get("window"),
                    "pilots": scorecards["pilots"]["window"],
                    "model_rank": rank["window"] if rank is not None else None},
        "model_rank": {"file": "rank.json", "settle_lag": rank.get("settle_lag"),
                       "qualified": rank.get("qualified"), "scales_source": rank.get("scales_source"),
                       "window": rank.get("window")} if rank is not None else None,
        "mvp": {"rule": RULE, "models": [
            {"model": row["model"], "rank": row["rank"], "rank_label": row.get("rank_label"),
             "score": row["score"], "interval": row.get("interval"), "units": row["units"],
             "crews": row.get("crews") or []} for row in band]} if band else None,
        "reason": None if band else why,
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
    index.write_text(note_text(day, scorecards, band, why, who, data_rel, a.fallback_crew), encoding="utf-8")
    named = names(row["model"] for row in band) if band else "none"
    print(f"wrote {index} (draft) and {data}; MVP {named}; writer {who['crew']}", file=sys.stderr)


if __name__ == "__main__":
    main()
