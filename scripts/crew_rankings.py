#!/usr/bin/env python3
"""Build the data for a weekly crew-rankings note.

Reads Orbit's implementer, reviewer and pilot scorecards for one window and
writes, into the note's directory:

- all-tiers.csv: implementer crews ranked on the all-tiers score;
- by-tier.csv: one row per crew, model and tier with 10 or more tasks;
- reviewers.csv, pilots.csv: the ranked reviewer and pilot crews;
- tables.md: the Markdown tables the note embeds, each with a one-line score key;
- facts.json: the window, the tiers shown, and the MVP of the week, for the prose.

tables.md and facts.json are working files: delete them before the note ships.

Usage, on the Orbit owner host:

    python3 scripts/crew_rankings.py notes/crew-rankings-<date> [--window 7d]
        [--workspace orbit] [--from <dir>]

--from reads saved `--json` output instead of calling orbit: per-task.json,
by-type.json and rows.json (implementers, with --per-task, --by-type and
neither), reviewers.json and pilots.json.

The method is on the standing page notes/crew-rankings-method. In short:

- All tiers ranks the implementers scorecard rows. Their score is already
  adjusted for each crew's tier mix, so crews on different tiers compare.
- A tier table ranks by the dashboard tier score (`--by-type` crew_mean) and
  appears only when MIN_CREWS or more crews have MIN_TASKS tasks on that tier.
- Reviewers and pilots rank the scorecard's ranked rows (at or above its
  minimum support). Their scores centre on the fleet average, not 100.
- The MVP is the crew, across all shown tables, with the largest lead over its
  table's #2, in units of the table's scale: 100 for implementer tables, the
  fleet average for reviewers and pilots.

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
MIN_CREWS = 3
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


def write_csv(path, rows):
    if not rows:
        path.unlink(missing_ok=True)
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--window", default="7d")
    ap.add_argument("--workspace", default="orbit")
    ap.add_argument("--from", dest="source")
    a = ap.parse_args()

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

    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    effort = efforts(rows, reviewers, pilots)
    eff = lambda crew: effort.get(crew, "unknown")

    # All tiers: the implementers rows, already adjusted for tier mix.
    all_rows = [{
        "rank": i, "crew": r["crew"], "model": r["model"], "effort": eff(r["crew"]),
        "tasks": r["units"], "score": round(r["score"], 1),
        "landed_pct": round(r["counts"]["weighted_landed"] / r["units"] * 100, 1),
    } for i, r in enumerate((r for r in ranked(rows) if r["units"] >= MIN_TASKS), 1)]
    write_csv(out / "all-tiers.csv", all_rows)

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
    write_csv(out / "by-tier.csv", tier_rows)
    per_tier = {t: [r for r in tier_rows if r["tier"] == t] for t in TIERS}
    shown = [t for t in TIERS if len(per_tier[t]) >= MIN_CREWS]

    # Reviewers and pilots: the scorecard's ranked rows.
    def role_rows(card):
        return [{
            "rank": i, "crew": r["crew"], "model": r["model"], "effort": eff(r["crew"]),
            "units": r["units"], "score": round(r["score"], 1),
            "fleet_average": card["fleet_average"],
            **({"provisional": r["provisional"]} if card.get("provisional") is not None else {}),
        } for i, r in enumerate(ranked(card), 1)]

    rev_rows, pil_rows = role_rows(reviewers), role_rows(pilots)
    write_csv(out / "reviewers.csv", rev_rows)
    write_csv(out / "pilots.csv", pil_rows)

    # MVP: the largest lead over its own table's #2, scaled by the table's centre.
    tables = [("all tiers", all_rows, "tasks", 100.0)]
    tables += [(f"{t} tier", per_tier[t], "tasks", 100.0) for t in shown]
    tables += [("reviewers", rev_rows, "units", reviewers["fleet_average"]),
               ("pilots", pil_rows, "units", pilots["fleet_average"])]
    leads = []
    for name, trows, unit, scale in tables:
        if len(trows) < 2:
            continue
        top, second = trows[0], trows[1]
        leads.append({
            "table": name, "crew": top["crew"], "model": top["model"], "effort": top["effort"],
            "score": top["score"], "units": top[unit],
            "runner_up": second["crew"], "runner_up_score": second["score"],
            "lead_points": round(top["score"] - second["score"], 1), "scale": scale,
            "lead_scaled": round((top["score"] - second["score"]) / scale, 3),
        })
    leads.sort(key=lambda x: -x["lead_scaled"])

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
    (out / "tables.md").write_text("\n".join(md))

    facts = {
        "window": a.window, "since": per_task["since"], "computed_at": per_task["computed_at"],
        "task_attempts": len(per_task["tasks"]),
        "min_support": {"implementers": rows["min_support"], "reviewers": reviewers["min_support"],
                        "pilots": pilots["min_support"], "tier_tasks": MIN_TASKS, "tier_crews": MIN_CREWS},
        "fleet_average": {"implementers": rows["fleet_average"], "reviewers": reviewers["fleet_average"],
                          "pilots": pilots["fleet_average"]},
        "reviews_provisional": prov, "reviews_settled": settled,
        "tiers_shown": shown,
        "tiers_omitted": {t: [r["crew"] for r in per_tier[t]] for t in TIERS if t not in shown},
        "ranked": {"all_tiers": len(all_rows), "reviewers": len(rev_rows), "pilots": len(pil_rows),
                   **{t: len(per_tier[t]) for t in shown}},
        "models": sorted({(r["crew"], r["model"]) for r in all_rows + tier_rows + rev_rows + pil_rows}),
        "mvp": leads[0] if leads else None,
        "leads": leads,
    }
    (out / "facts.json").write_text(json.dumps(facts, indent=2) + "\n")


if __name__ == "__main__":
    main()
