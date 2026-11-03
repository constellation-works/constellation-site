#!/usr/bin/env python3
"""Build the data for a weekly crew-rankings note.

Reads Orbit's implementer scorecard for one window and writes, into the note's
directory:

- by-tier.csv: one row per crew, model and tier with 10 or more tasks;
- regressions.csv: per-crew escaped regressions against expected, all tiers;
- tables.md: the Markdown tables the note embeds;
- facts.json: the window and headline counts the prose cites.

Usage, on the Orbit owner host:

    python3 scripts/crew_rankings.py notes/crew-rankings-<date> [--window 7d]
        [--workspace orbit] [--from <dir with per-task.json, by-type.json, rows.json>]

Ranking and rates follow notes/crew-rankings-2026-11-03: each tier is ranked by
the dashboard tier score (`--by-type` crew_mean); reworked is the share of tasks
with any crew-caused rework, with a 95% Wilson interval. Rows with no recorded
model are dropped.
"""

import argparse
import collections
import csv
import json
import math
import pathlib
import subprocess

MIN_TASKS = 10
TIERS = ("low", "medium", "hard", "xhard")


def scorecard(window, workspace, *flags):
    cmd = ["orbit", "--workspace", workspace, "agents", "scorecard",
           "--role", "implementers", "--window", window, "--json", *flags]
    return json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True).stdout)


def wilson(k, n, z=1.96):
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half) * 100, min(1.0, centre + half) * 100


def pct(x):
    return f"{x:g}%" if x in (0, 100) else f"{x:.1f}%"


def efforts(rows):
    """Crew -> its reasoning efforts, most-invoked first ("high, medium")."""
    out = {}
    for row in rows:
        seen = collections.Counter()
        for e in row.get("effort_breakdown") or []:
            seen[e.get("reasoning_effort") or "unknown"] += e.get("invocations", 0)
        if seen:
            out.setdefault(row["crew"], ", ".join(k for k, _ in seen.most_common()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--window", default="7d")
    ap.add_argument("--workspace", default="orbit")
    ap.add_argument("--from", dest="source")
    a = ap.parse_args()

    if a.source:
        src = pathlib.Path(a.source)
        per_task, by_type, rows = (json.loads((src / f).read_text())
                                   for f in ("per-task.json", "by-type.json", "rows.json"))
    else:
        per_task = scorecard(a.window, a.workspace, "--per-task")
        by_type = scorecard(a.window, a.workspace, "--by-type")
        rows = scorecard(a.window, a.workspace)

    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    effort = efforts(rows["rows"])

    score = {(c["tier"], c["crew"], c["model"]): c["crew_mean"] for c in by_type["cells"]}
    agg = collections.defaultdict(collections.Counter)
    for t in per_task["tasks"]:
        crew = t["crew"]
        if not crew or crew == "system" or t["model"] == "model unknown" or t["tier"] not in TIERS:
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
            "tier": tier, "crew": crew, "model": model, "effort": effort.get(crew, "unknown"),
            "tasks": n, "score": round(score.get((tier, crew, model), 100.0), 1),
            "landed_pct": round(g["landed"] / n * 100, 1),
            "reworked_pct": round(g["reworked"] / n * 100, 1),
            "reworked_lo": round(lo, 1), "reworked_hi": round(hi, 1),
            "prelanding_repaired_pct": round(g["repaired"] / n * 100, 1),
            "prelanding_rejected_pct": round(g["rejected"] / n * 100, 1),
            "prelanding_first_pass_accept_pct": round(g["first_pass"] / n * 100, 1),
        })
    tier_rows.sort(key=lambda r: (TIERS.index(r["tier"]), -r["score"]))
    with open(out / "by-tier.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(tier_rows[0]))
        w.writeheader()
        w.writerows(tier_rows)

    reg_rows = []
    for row in rows["rows"]:
        if row["units"] < MIN_TASKS or row["model"] == "model unknown":
            continue
        st = {s["key"]: s["value"] for s in row["stats"]}
        actual, residual = st.get("escaped_regressions"), st.get("regression_residual")
        if actual is None or residual is None:
            continue
        reg_rows.append({
            "crew": row["crew"], "model": row["model"], "effort": effort.get(row["crew"], "unknown"),
            "tasks": row["units"], "tiers": st.get("tasks_by_tier", ""),
            "regressions": actual, "per_task": round(actual / row["units"], 2),
            "expected": round(actual - residual, 1), "difference": round(residual, 1),
        })
    reg_rows.sort(key=lambda r: r["per_task"])
    with open(out / "regressions.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(reg_rows[0]))
        w.writeheader()
        w.writerows(reg_rows)

    md = []
    for tier in TIERS:
        ranked = [r for r in tier_rows if r["tier"] == tier]
        if not ranked:
            continue
        md += [f"### {tier.capitalize()}", "",
               "| Rank | Crew · effort | Score | Tasks | Landed | Reworked (95%) |",
               "|--:|---|--:|--:|--:|--:|"]
        for i, r in enumerate(ranked, 1):
            md.append(f"| {i} | {r['crew']} · {r['effort']} | {r['score']:.1f} | {r['tasks']} | "
                      f"{pct(r['landed_pct'])} | {pct(r['reworked_pct'])} ({r['reworked_lo']}–{r['reworked_hi']}) |")
        md.append("")
    md += ["### Escaped regressions", "",
           "| Crew · effort | Tasks | Regressions | Per task | Expected | Difference |",
           "|---|--:|--:|--:|--:|--:|"]
    for r in reg_rows:
        md.append(f"| {r['crew']} · {r['effort']} | {r['tasks']} | {r['regressions']:g} | "
                  f"{r['per_task']:.2f} | {r['expected']:.1f} | {r['difference']:+.1f} |")
    (out / "tables.md").write_text("\n".join(md) + "\n")

    facts = {
        "window": a.window, "since": per_task["since"], "computed_at": per_task["computed_at"],
        "task_attempts": len(per_task["tasks"]), "ranked_pairs": len(tier_rows),
        "pairs_landed_93_or_more": sum(r["landed_pct"] >= 93 for r in tier_rows),
        "models": sorted({(r["crew"], r["model"]) for r in tier_rows}),
    }
    (out / "facts.json").write_text(json.dumps(facts, indent=2) + "\n")


if __name__ == "__main__":
    main()
