#!/usr/bin/env python3
"""Build the data for a weekly crew-rankings note.

Reads Orbit's implementer, reviewer and pilot scorecards for one window and
writes, into the note's directory:

- all-tiers.csv: implementer crews ranked on the all-tiers score;
- by-tier.csv: one row per crew, model and tier with 10 or more tasks;
- reviewers.csv, pilots.csv: the ranked reviewer and pilot crews;
- tables.md: the Markdown tables the note embeds, each with a one-line score key;
- facts.json: the window, the tiers shown, the MVP of the week and the crew that
  writes the note (the MVP's crew, or --fallback-crew), for the prose.

tables.md and facts.json are working files: delete them before the note ships.

Usage, on the Orbit owner host:

    python3 scripts/crew_rankings.py notes/crew-rankings-<date> [--window 7d]
        [--workspace orbit] [--from <dir>] [--fallback-crew opus] [--crews a,b,...]
    python3 scripts/crew_rankings.py --writer-only [same options]   # writer JSON only

--from reads saved `--json` output instead of calling orbit: per-task.json,
by-type.json and rows.json (implementers, with --per-task, --by-type and
neither), reviewers.json and pilots.json.

The method is on the standing page notes/crew-rankings-method. In short:

- All tiers ranks the implementers scorecard rows. Their score is already
  adjusted for each crew's tier mix, so crews on different tiers compare.
- A tier table ranks by the dashboard tier score (`--by-type` crew_mean) and
  appears only when MIN_MODELS or more distinct models have MIN_TASKS tasks on
  that tier (opus and opus@medium count once).
- Reviewers and pilots rank the scorecard's ranked rows (at or above its
  minimum support). Their scores centre on the fleet average, not 100.
- The MVP is a model, scored on the shown tier tables only: 5, 3 and 1 points
  for 1st, 2nd and 3rd, each model counted once per tier through its best
  crew. Ties go to the larger summed margin over the next distinct model, then
  more tasks, then --fallback-crew. Its best crew writes the note.

Rows with no recorded model are dropped everywhere.
"""

import argparse
import collections
import csv
import json
import math
import pathlib
import subprocess

MIN_TASKS = 10
MIN_MODELS = 3
TIERS = ("low", "medium", "hard", "xhard")
UNKNOWN_MODEL = "model unknown"


def scorecard(window, workspace, role, *flags):
    cmd = ["orbit", "--workspace", workspace, "agents", "scorecard",
           "--role", role, "--window", window, "--json", *flags]
    return json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True).stdout)


def wilson(k, n, z=1.96):
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half) * 100, min(1.0, centre + half) * 100


def pct(x):
    return f"{x:g}%" if x in (0, 100) else f"{x:.1f}%"


def efforts(*cards):
    """Crew -> its reasoning efforts, most-invoked first ("high, medium").

    A crew's own row is read first. A crew whose row has no dispatch evidence
    (reviewers often don't) falls back to its runs anywhere in the workspace,
    from each card's top-level effort_breakdown.
    """
    out = {}
    pools = [e for card in cards for row in card["rows"] for e in row.get("effort_breakdown") or []]
    pools += [e for card in cards for e in card.get("effort_breakdown") or []]
    seen = collections.defaultdict(collections.Counter)
    for e in pools:
        effort = e.get("reasoning_effort")
        if effort and effort != "unknown" and e.get("invocations"):
            seen[e["crew"]][effort] += e["invocations"]
    for crew, c in seen.items():
        out[crew] = ", ".join(k for k, _ in c.most_common())
    return out


def ranked(card):
    """The scorecard's ranked rows (minimum support met, judged), in its rank order."""
    rows = [r for r in card["rows"]
            if r.get("rank") is not None and not r.get("below_support") and not r.get("unjudged")
            and r["model"] != UNKNOWN_MODEL]
    return sorted(rows, key=lambda r: r["rank"])


def term_key(card, unit, centre):
    """One line naming what the score credits and debits, and where it centres."""
    credit = [t["label"].lower() for t in card["terms"] if t["weight"] > 0]
    debit = [t["label"].lower() for t in card["terms"] if t["weight"] < 0]
    return (f"Score: per 100 {unit}, credit for {', '.join(credit)}; "
            f"debits for {', '.join(debit)}. {centre}")


PLACE_POINTS = {1: 5, 2: 3, 3: 1}
ORDINAL = {1: "1st", 2: "2nd", 3: "3rd"}


def ordinal(n):
    return ORDINAL.get(n, f"{n}th")


def mvp_points(per_tier, shown):
    """Score models on the shown tier tables: 5/3/1 points for 1st/2nd/3rd.

    A model counts once per tier, through its best-scoring crew, and is placed
    against the next distinct model. Its margin is the sum, over the tiers, of
    its score minus the next distinct model's score (0 in last place). Units
    are all its crews' tasks on those tiers. Returns the models ranked by
    points, then margin, then units.
    """
    models = {}
    for tier in shown:
        best = {}
        for r in sorted(per_tier[tier], key=lambda r: -r["score"]):
            best.setdefault(r["model"], r)
        order = list(best.values())
        for i, r in enumerate(order, 1):
            m = models.setdefault(r["model"], {"model": r["model"], "points": 0, "margin": 0.0,
                                                "units": 0, "places": {}})
            below = order[i]["score"] if i < len(order) else r["score"]
            m["points"] += PLACE_POINTS.get(i, 0)
            m["margin"] += r["score"] - below
            m["places"][tier] = {"place": i, "points": PLACE_POINTS.get(i, 0), "crew": r["crew"],
                                 "score": r["score"], "margin": round(r["score"] - below, 1)}
        for r in per_tier[tier]:
            models[r["model"]]["units"] += r["tasks"]
    for m in models.values():
        m["margin"] = round(m["margin"], 1)
        # The model's best crew: its best placement, then its higher score there.
        m["best_crew"] = min(m["places"].values(), key=lambda p: (p["place"], -p["score"]))["crew"]
    return sorted(models.values(), key=lambda m: (-m["points"], -m["margin"], -m["units"]))


def pick_mvp(ranking):
    """The top model and the tie-break that settled it (None if no tier counted)."""
    if not ranking:
        return None
    top = ranking[0]
    tied = ranking[1:2] and ranking[1]
    if not tied or tied["points"] != top["points"]:
        rule = "points"
    elif tied["margin"] != top["margin"]:
        rule = "margin"
    elif tied["units"] != top["units"]:
        rule = "units"
    else:
        rule = "fallback"
    return {"model": top["model"], "best_crew": top["best_crew"], "points": top["points"],
            "margin": top["margin"], "units": top["units"], "tie_break": rule,
            "tiers": {t: p for t, p in top["places"].items()}}


def pick_writer(mvp, fallback, crews):
    """The crew that writes the note: the MVP model's best crew, without @effort.

    Falls back to `fallback` when no tier table counts, when a tie survives
    points, margin and units, or when the crew isn't one of `crews` (the
    crews configured in the workspace; None skips that check).
    """
    crew = mvp["best_crew"].split("@", 1)[0] if mvp else None
    ok = (mvp is not None and mvp["tie_break"] != "fallback"
          and (crews is None or crew in crews))
    return {
        "crew": crew if ok else fallback, "source": "mvp" if ok else "fallback",
        "mvp_crew_row": mvp and mvp["best_crew"], "model": mvp and mvp["model"],
        "points": mvp and mvp["points"], "margin": mvp and mvp["margin"],
        "units": mvp and mvp["units"], "tie_break": mvp and mvp["tie_break"],
    }


def write_csv(path, rows):
    if path is None:
        return
    if not rows:
        path.unlink(missing_ok=True)
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?")
    ap.add_argument("--window", default="7d")
    ap.add_argument("--workspace", default="orbit")
    ap.add_argument("--from", dest="source")
    ap.add_argument("--fallback-crew", default="opus",
                    help="crew that writes the note when no MVP qualifies (default opus)")
    ap.add_argument("--crews", help="comma list of crews configured in the workspace; "
                    "an MVP crew outside it hands the note to --fallback-crew")
    ap.add_argument("--writer-only", action="store_true",
                    help="print only the writer JSON on stdout and write no files")
    a = ap.parse_args()
    if not a.out and not a.writer_only:
        ap.error("out is required unless --writer-only is given")
    crews = {c.strip() for c in a.crews.split(",") if c.strip()} if a.crews else None

    if a.source:
        src = pathlib.Path(a.source)
        per_task, by_type, rows, reviewers, pilots = (
            json.loads((src / f).read_text())
            for f in ("per-task.json", "by-type.json", "rows.json", "reviewers.json", "pilots.json"))
    else:
        per_task = scorecard(a.window, a.workspace, "implementers", "--per-task")
        by_type = scorecard(a.window, a.workspace, "implementers", "--by-type")
        rows = scorecard(a.window, a.workspace, "implementers")
        reviewers = scorecard(a.window, a.workspace, "reviewers")
        pilots = scorecard(a.window, a.workspace, "pilots")

    out = None if a.writer_only else pathlib.Path(a.out)
    if out:
        out.mkdir(parents=True, exist_ok=True)
    path = lambda name: out / name if out else None
    effort = efforts(rows, reviewers, pilots)
    eff = lambda crew: effort.get(crew, "unknown")

    # All tiers: the implementers rows, already adjusted for tier mix.
    all_rows = [{
        "rank": i, "crew": r["crew"], "model": r["model"], "effort": eff(r["crew"]),
        "tasks": r["units"], "score": round(r["score"], 1),
        "landed_pct": round(r["counts"]["weighted_landed"] / r["units"] * 100, 1),
    } for i, r in enumerate((r for r in ranked(rows) if r["units"] >= MIN_TASKS), 1)]
    write_csv(path("all-tiers.csv"), all_rows)

    # By tier: raw rates from --per-task, tier scores from --by-type.
    score = {(c["tier"], c["crew"], c["model"]): c["crew_mean"] for c in by_type["cells"]}
    agg = collections.defaultdict(collections.Counter)
    for t in per_task["tasks"]:
        crew = t["crew"]
        if not crew or crew == "system" or t["model"] == UNKNOWN_MODEL or t["tier"] not in TIERS:
            continue
        g = agg[(t["tier"], crew, t["model"])]
        counts = t["counts"]
        g["n"] += 1
        g["landed"] += counts["weighted_landed"]
        g["reworked"] += counts["crew_rework"] > 0
        g["repaired"] += counts["reviewer_repairs"] > 0
        g["rejected"] += counts["review_rejects"] > 0
        g["first_pass"] += counts["first_pass_accepts"] > 0

    tier_rows = []
    for (tier, crew, model), g in agg.items():
        n = g["n"]
        if n < MIN_TASKS:
            continue
        lo, hi = wilson(g["reworked"], n)
        tier_rows.append({
            "tier": tier, "crew": crew, "model": model, "effort": eff(crew),
            "tasks": n, "score": round(score.get((tier, crew, model), 100.0), 1),
            "landed_pct": round(g["landed"] / n * 100, 1),
            "reworked_pct": round(g["reworked"] / n * 100, 1),
            "reworked_lo": round(lo, 1), "reworked_hi": round(hi, 1),
            "prelanding_repaired_pct": round(g["repaired"] / n * 100, 1),
            "prelanding_rejected_pct": round(g["rejected"] / n * 100, 1),
            "prelanding_first_pass_accept_pct": round(g["first_pass"] / n * 100, 1),
        })
    tier_rows.sort(key=lambda r: (TIERS.index(r["tier"]), -r["score"]))
    write_csv(path("by-tier.csv"), tier_rows)
    per_tier = {t: [r for r in tier_rows if r["tier"] == t] for t in TIERS}
    shown = [t for t in TIERS if len({r['model'] for r in per_tier[t]}) >= MIN_MODELS]

    # Reviewers and pilots: the scorecard's ranked rows.
    def role_rows(card):
        return [{
            "rank": i, "crew": r["crew"], "model": r["model"], "effort": eff(r["crew"]),
            "units": r["units"], "score": round(r["score"], 1),
            "fleet_average": card["fleet_average"],
            **({"provisional": r["provisional"]} if card.get("provisional") is not None else {}),
        } for i, r in enumerate(ranked(card), 1)]

    rev_rows, pil_rows = role_rows(reviewers), role_rows(pilots)
    write_csv(path("reviewers.csv"), rev_rows)
    write_csv(path("pilots.csv"), pil_rows)

    # MVP: points for placing on the shown tier tables, by model.
    ranking = mvp_points(per_tier, shown)
    mvp = pick_mvp(ranking)
    writer = pick_writer(mvp, a.fallback_crew, crews)
    if a.writer_only:
        print(json.dumps(writer))
        return

    # tables.md
    md = ["### All tiers", "",
          term_key(rows, "tasks", "The expectations use the fleet's rates for each crew's own tier mix, "
                   "so 100 is the fleet average and crews on different tiers compare."), "",
          "| Rank | Crew · effort | Score | Tasks | Landed |",
          "|--:|---|--:|--:|--:|"]
    md += [f"| {r['rank']} | {r['crew']} · {r['effort']} | {r['score']:.1f} | {r['tasks']} | "
           f"{pct(r['landed_pct'])} |" for r in all_rows]
    md.append("")
    for tier in shown:
        md += [f"### {tier.capitalize()} tier", "",
               "Score: the dashboard tier score, against the fleet's rates on this tier; "
               "100 is the fleet average.", "",
               "| Rank | Crew · effort | Score | Tasks | Landed | Reworked (95%) |",
               "|--:|---|--:|--:|--:|--:|"]
        for i, r in enumerate(per_tier[tier], 1):
            md.append(f"| {i} | {r['crew']} · {r['effort']} | {r['score']:.1f} | {r['tasks']} | "
                      f"{pct(r['landed_pct'])} | {pct(r['reworked_pct'])} ({r['reworked_lo']}–{r['reworked_hi']}) |")
        md.append("")
    prov = reviewers.get("provisional")
    settled = sum(r["units"] for r in reviewers["rows"])
    share = f"All {settled}" if prov == settled else f"{prov} of the {settled}"
    prov_note = (f" {share} reviews in the window are under 30 days old, "
                 "so missed regressions can still lower these scores.") if prov else ""
    for title, card, unit, trows, extra in (
            ("Reviewers", reviewers, "settled reviews", rev_rows, prov_note),
            ("Pilots", pilots, "assessed tasks", pil_rows, "")):
        md += [f"### {title}", "",
               term_key(card, unit, f"The fleet average is {card['fleet_average']:.1f}, not 100.{extra}"), "",
               f"| Rank | Crew · effort | Score | {unit.split()[-1].capitalize()} |",
               "|--:|---|--:|--:|"]
        md += [f"| {r['rank']} | {r['crew']} · {r['effort']} | {r['score']:.1f} | {r['units']} |" for r in trows]
        md.append("")
    md += ["### MVP points", ""]
    if ranking:
        md += ["Points: 5, 3 and 1 for 1st, 2nd and 3rd on each tier table above, by model "
               "through its best crew; ties go to the larger margin over the next model, "
               "then more tasks.", "",
               "| Model | " + " | ".join(f"{t.capitalize()}" for t in shown) + " | Margin | Points |",
               "|---|" + "--:|" * len(shown) + "--:|--:|"]
        for m in ranking:
            cells = [f"{ordinal(m['places'][t]['place'])} · {m['places'][t]['points']}"
                     if t in m["places"] else "–" for t in shown]
            md.append(f"| {m['model']} ({m['best_crew']}) | " + " | ".join(cells)
                      + f" | {m['margin']:+.1f} | {m['points']} |")
    else:
        md.append(f"No tier had crews on {MIN_MODELS} or more models this week, so there is "
                  f"no MVP, and the configured crew ({a.fallback_crew}) writes the note.")
    md.append("")
    (out / "tables.md").write_text("\n".join(md))

    facts = {
        "window": a.window, "since": per_task["since"], "computed_at": per_task["computed_at"],
        "task_attempts": len(per_task["tasks"]),
        "min_support": {"implementers": rows["min_support"], "reviewers": reviewers["min_support"],
                        "pilots": pilots["min_support"], "tier_tasks": MIN_TASKS, "tier_models": MIN_MODELS},
        "fleet_average": {"implementers": rows["fleet_average"], "reviewers": reviewers["fleet_average"],
                          "pilots": pilots["fleet_average"]},
        "reviews_provisional": prov, "reviews_settled": settled,
        "tiers_shown": shown,
        "tiers_omitted": {t: [r["crew"] for r in per_tier[t]] for t in TIERS if t not in shown},
        "ranked": {"all_tiers": len(all_rows), "reviewers": len(rev_rows), "pilots": len(pil_rows),
                   **{t: len(per_tier[t]) for t in shown}},
        "models": sorted({(r["crew"], r["model"]) for r in all_rows + tier_rows + rev_rows + pil_rows}),
        "mvp": mvp,
        "writer": writer,
        "mvp_points": ranking,
    }
    (out / "facts.json").write_text(json.dumps(facts, indent=2) + "\n")


if __name__ == "__main__":
    main()
