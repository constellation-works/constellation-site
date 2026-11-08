#!/usr/bin/env python3
"""Build the data for a weekly crew-rankings note.

Reads Orbit's implementer, reviewer and pilot scorecards for one window and
writes, into the note's directory:

- all-tiers.csv: implementer crews ranked on the all-tiers score;
- by-tier.csv: one row per crew, model and tier with 10 or more tasks;
- reviewers.csv, pilots.csv: the ranked reviewer and pilot crews;
- crown.csv: one row per implementer model, its crews pooled, with its crown score;
- tables.md: the note's generated body (the Implementer MVP section and every board, each
  with its exact UTC window and a one-line score key);
- facts.json: the windows, the tiers shown, the Implementer MVP crown table
  and the crew that writes the note (the Implementer MVP's crew, or
  --fallback-crew).

With --archive DIR it also freezes this run's inputs there (the scorecard
payloads, the per-task export cut to the fields this script reads, and
facts.json), so `--from DIR` reproduces the note exactly.

tables.md and facts.json are working files: delete them before the note ships.

Usage, on the Orbit owner host:

    python3 scripts/crew_rankings.py notes/crew-rankings-<date> [--window 7d]
        [--workspace orbit] [--reviewer-window 30d] [--from <dir>]
        [--fallback-crew opus] [--crews a,b,...]
    python3 scripts/crew_rankings.py --writer-only [same options]
        # prints only the writer JSON: the Implementer MVP's crew, or the fallback
    python3 scripts/crew_rankings.py <out> --archive data/crew-rankings/<date>
        # also freezes this run's inputs; rerun later with --from that directory

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
- The award is the Implementer MVP, a model, by the phase 1 crown (Daniel,
  2026-11-08; constellation docs/discussion/synthesis.md v2). Implementers
  only, on the all-tiers window. Each model's crews are pooled before scoring,
  never the best crew: its raw score is recomputed from the crews' summed
  counts, expectations and term units where the payload has them, otherwise
  the units-weighted mean of the crews' raw scores (an approximation for terms
  with their own denominator). The crown score shrinks that once, (n * raw +
  K * avg_loo) / (n + K) with K = 30, where avg_loo is the units-weighted mean
  pooled raw of every other model in the field. The field is the models with
  10 or more pooled units, and a crown needs 3 of them. Highest crown wins; an
  exact tie gives co-Implementer MVPs, and the alphabetically first writes.
  No margin or volume tie-breaks. Reviewer and pilot boards are shown without
  points until settled windows and noise scales exist (ORB-23066).
- Reviewers are read on --reviewer-window (30d), not --window.

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


def day(ts):
    """The YYYY-MM-DD date of an RFC 3339 timestamp."""
    return ts[:10]


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


ORDINAL = {1: "1st", 2: "2nd", 3: "3rd"}
CROWN_K = 30
K_SENSITIVITY = (10, 30, 60)
SCORE_NOTE = ("not scored until settled windows and noise scales exist (ORB-23066)")


def ordinal(n):
    return ORDINAL.get(n, f"{n}th")


def utc(ts):
    """An RFC 3339 timestamp to the second, in UTC (2026-11-08T06:03:37Z)."""
    return ts[:19] + "Z"


def window_line(card):
    return f"Window: {utc(card['since'])} to {utc(card['computed_at'])} (UTC)."


def base_crew(crew):
    return crew.split("@", 1)[0]


def row_raw(rows, terms):
    """Raw score of pooled rows from their summed counts, expectations and units.

    Each term's denominator is its term_units when present, else the row's
    units (agent-scorecards §5.2). A term with no units is unmeasured and adds
    nothing. Returns None when the payload lacks what this needs.
    """
    try:
        base = {r["score_base"] for r in rows}
        if len(base) != 1:
            return None
        raw = base.pop()
        for t in terms:
            key, w = t["key"], t["weight"]
            actual = sum(r["counts"][key] for r in rows)
            expected = sum(r["expected"][key] for r in rows)
            units = sum((r.get("term_units") or {}).get(key, r["units"]) for r in rows)
            if units:
                raw += w * (actual - expected) * 100 / units
        return raw
    except (KeyError, TypeError):
        return None


def rounding(row, terms):
    """How far a recomputed raw can drift from the reported one by rounding alone.

    The payload rounds counts and expectations to 2 decimals (±0.005 each) and
    raw to 2 decimals, and each term divides by its own units.
    """
    drift = 0.005
    for t in terms:
        units = (row.get("term_units") or {}).get(t["key"], row["units"])
        if units:
            drift += abs(t["weight"]) * 2 * 0.005 * 100 / units
    return drift


def pool_models(card):
    """Pool the implementer scorecard's crews by model, before any shrinkage.

    Every judged row with a known model counts, below support or not: pooling
    is how a model's small crews are read, and taking the best crew is not
    allowed. The pooled raw score is recomputed from the crews' summed counts,
    expectations and term units, which is exact, when the payload has them and
    each crew's own raw recomputes to its reported raw. Otherwise it is the
    units-weighted mean of the crews' raw scores, which approximates the pooled
    observations and isn't exact for terms with their own denominator (the
    review terms, per reviewed delivery). `method` says which was used.
    """
    models, by_model = {}, collections.defaultdict(list)
    for r in card["rows"]:
        if r.get("unjudged") or r["model"] == UNKNOWN_MODEL or not r["units"]:
            continue
        by_model[r["model"]].append(r)
    terms = card["terms"]
    for name, rs in by_model.items():
        units = sum(r["units"] for r in rs)
        mean = sum(r["units"] * r["raw"] for r in rs) / units
        exact = row_raw(rs, terms)
        consistent = exact is not None and all(
            (rr := row_raw([r], terms)) is not None and abs(rr - r["raw"]) <= rounding(r, terms)
            for r in rs)
        crews = sorted(({"crew": r["crew"], "units": r["units"], "raw": round(r["raw"], 2),
                         "score": round(r["score"], 1)} for r in rs), key=lambda c: -c["units"])
        models[name] = {"model": name, "units": units, "crews": crews, "k": len(crews),
                        "raw": exact if consistent else mean,
                        "raw_mean_of_crews": mean,
                        "method": "pooled counts" if consistent else "mean of crew raws"}
    return models


def crown_scores(models, k):
    """Shrink each field model once toward the other models' pooled mean.

    avg_loo is the units-weighted mean pooled raw of every other model in the
    field, so none of the model's own crews are in its target.
    """
    field = {name: m for name, m in models.items() if m["units"] >= MIN_TASKS}
    out = {}
    for name, m in field.items():
        others = [o for o in field.values() if o is not m]
        n_o = sum(o["units"] for o in others)
        avg_loo = sum(o["units"] * o["raw"] for o in others) / n_o if n_o else m["raw"]
        out[name] = {"avg_loo": avg_loo,
                     "crown": (m["units"] * m["raw"] + k * avg_loo) / (m["units"] + k)}
    return out


def crown_winners(scores):
    """The model or models with the highest crown score, exact ties kept."""
    if not scores:
        return []
    top = max(s["crown"] for s in scores.values())
    return sorted(name for name, s in scores.items() if s["crown"] == top)


def crown(models):
    """The phase 1 crown: field, scores at CROWN_K, winners and K sensitivity."""
    field = sorted(name for name, m in models.items() if m["units"] >= MIN_TASKS)
    qualified = len(field) >= MIN_MODELS
    scores = crown_scores(models, CROWN_K)
    winners = crown_winners(scores) if qualified else []
    sens = {k: crown_winners(crown_scores(models, k)) if qualified else [] for k in K_SENSITIVITY}
    order = sorted(scores, key=lambda name: -scores[name]["crown"])
    return {"k": CROWN_K, "field": field, "qualified": qualified, "winners": winners,
            "k_sensitivity": sens, "order": order, "scores": scores}


def pick_writer(models, c, fallback, crews):
    """The crew that writes the note: the Implementer MVP's crew, without @effort.

    With co-Implementer MVPs, the alphabetically first model writes. A model's crew is its
    largest base crew by units. Falls back to `fallback` when no crown is
    awarded or the crew isn't one of `crews` (None skips that check).
    """
    mvp = c["winners"][0] if c["winners"] else None
    crew = None
    if mvp:
        by_base = collections.Counter()
        for cr in models[mvp]["crews"]:
            by_base[base_crew(cr["crew"])] += cr["units"]
        crew = by_base.most_common(1)[0][0]
    ok = mvp is not None and (crews is None or crew in crews)
    s = c["scores"].get(mvp) if mvp else None
    return {
        "crew": crew if ok else fallback, "source": "implementer_mvp" if ok else "fallback",
        "model": mvp, "co_implementer_mvps": c["winners"] if len(c["winners"]) > 1 else [],
        "crown": round(s["crown"], 2) if s else None,
        "raw": round(models[mvp]["raw"], 2) if mvp else None,
        "units": models[mvp]["units"] if mvp else None,
        "implementer_mvp_crew": crew,
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
    ap.add_argument("--reviewer-window", default="30d",
                    help="window for the reviewer scorecard (default 30d)")
    ap.add_argument("--from", dest="source")
    ap.add_argument("--fallback-crew", default="opus",
                    help="crew that writes the note when no Implementer MVP is crowned (default opus)")
    ap.add_argument("--crews", help="comma list of crews configured in the workspace; "
                    "an Implementer MVP crew outside it hands the note to --fallback-crew")
    ap.add_argument("--archive", help="freeze this run's inputs and facts.json in this directory")
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
        reviewers = scorecard(a.reviewer_window, a.workspace, "reviewers")
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

    # Implementer MVP: the phase 1 crown, implementers only, crews pooled by model.
    models = pool_models(rows)
    c = crown(models)
    writer = pick_writer(models, c, a.fallback_crew, crews)
    crown_rows = [{
        "place": i, "model": name, "crews": " ".join(f"{cr['crew']}:{cr['units']}" for cr in models[name]["crews"]),
        "k": models[name]["k"], "pooled_units": models[name]["units"],
        "raw": round(models[name]["raw"], 2), "raw_method": models[name]["method"],
        "raw_mean_of_crews": round(models[name]["raw_mean_of_crews"], 2), "avg_loo": round(c["scores"][name]["avg_loo"], 2),
        "crown": round(c["scores"][name]["crown"], 2),
        "scorecard_scores": " ".join(f"{cr['crew']}:{cr['score']}" for cr in models[name]["crews"]),
    } for i, name in enumerate(c["order"], 1)]
    write_csv(path("crown.csv"), crown_rows)
    if a.writer_only:
        print(json.dumps(writer))
        return

    # tables.md: the note's generated body.
    winners = c["winners"]
    md = ["### Implementer MVP of the week", "",
          "This is the phase 1 interim, implementer-only crown, so it is the Implementer MVP, "
          "not an all-round MVP. Reviewer and pilot boards are shown below without points, "
          f"{SCORE_NOTE}.", ""]
    if not c["qualified"]:
        md += [f"No crown this week: fewer than {MIN_MODELS} models had {MIN_TASKS} or more "
               f"pooled tasks, so there is no Implementer MVP, and the configured crew "
               f"({a.fallback_crew}) writes the note.", ""]
    else:
        lead = " and ".join(winners)
        if len(winners) > 1:
            md += [f"Co-Implementer MVPs: {lead}, tied exactly on crown score "
                   f"{c['scores'][winners[0]]['crown']:.2f}. {winners[0]} writes the note, "
                   "as the alphabetically first.", ""]
        else:
            w = winners[0]
            md += [f"Implementer MVP: {w}, crown score {c['scores'][w]['crown']:.2f} on "
                   f"{models[w]['units']} pooled tasks (raw {models[w]['raw']:.2f}).", ""]
        if writer["source"] == "fallback":
            md += [f"The Implementer MVP's crew ({writer['implementer_mvp_crew']}) isn't "
                   f"configured here, so the configured crew ({a.fallback_crew}) writes the note.", ""]
    methods = {models[r["model"]]["method"] for r in crown_rows}
    pooled_line = ("Each model's raw score is recomputed from its crews' summed counts, "
                   "expectations and term units, so it is the score of the pooled tasks. (The "
                   "units-weighted mean of the crews' raw scores would only approximate it, and "
                   "not exactly for terms with their own denominator, such as the review terms "
                   "per reviewed delivery.)"
                   if methods == {"pooled counts"} else
                   "Each model's raw score is pooled from its crews: recomputed from their summed "
                   "counts where the payload allows, otherwise the units-weighted mean of the crews' "
                   "raw scores. That mean approximates scoring the pooled tasks and isn't exact for "
                   "terms with their own denominator, such as the review terms per reviewed delivery. "
                   "The Raw column says which.")
    md += [window_line(rows), "",
           "Crown score: a model's crews are pooled before scoring, never its best crew taken. "
           + pooled_line + f" That raw score is shrunk once, (n × raw + {CROWN_K} × avg) / "
           f"(n + {CROWN_K}), where n is the pooled tasks and avg is the units-weighted mean raw "
           "of every other model in the field. The field is the models with "
           f"{MIN_TASKS} or more pooled tasks. The scorecard score is each crew's own and isn't "
           "used for the crown.", "",
           "| Place | Model | Crews (k) | Pooled tasks | Raw | Crown score | Scorecard score |",
           "|--:|---|---|--:|--:|--:|---|"]
    for r in crown_rows:
        m = models[r["model"]]
        crews_s = ", ".join(f"{cr['crew']} ({cr['units']})" for cr in m["crews"])
        sc = ", ".join(f"{cr['crew']} {cr['score']:.1f}" for cr in m["crews"])
        raw_s = f"{m['raw']:.2f}" + ("" if m["method"] == "pooled counts" else " (mean)")
        md.append(f"| {ordinal(r['place'])} | {r['model']} | {crews_s} (k={m['k']}) | "
                  f"{m['units']} | {raw_s} | {r['crown']:.2f} | {sc} |")
    out_of_field = sorted(n for n in models if n not in c["scores"])
    if out_of_field:
        md += ["", "Outside the field (under "
               f"{MIN_TASKS} pooled tasks): " + ", ".join(
                   f"{n} ({models[n]['units']})" for n in out_of_field) + "."]
    if c["qualified"]:
        sens = "; ".join(f"K = {k}: {' and '.join(v)}" for k, v in c["k_sensitivity"].items())
        stable = len({tuple(v) for v in c["k_sensitivity"].values()}) == 1
        md += ["", "Volume check, the winner at each shrinkage strength K (a larger K favours "
               f"models with more tasks): {sens}. "
               + ("The winner doesn't depend on K." if stable else "The winner depends on K.")]
    md += ["", "Implementer MVP means the strongest observed implementer contribution under "
           "the fleet's actual assignments this week, not a verdict on a model's general "
           "capability.", ""]

    md += ["### All tiers", "", window_line(rows), "",
          term_key(rows, "tasks", "The expectations use the fleet's rates for each crew's own tier mix, "
                   "so 100 is the fleet average and crews on different tiers compare."), "",
          "| Rank | Crew · effort | Score | Tasks | Landed |",
          "|--:|---|--:|--:|--:|"]
    md += [f"| {r['rank']} | {r['crew']} · {r['effort']} | {r['score']:.1f} | {r['tasks']} | "
           f"{pct(r['landed_pct'])} |" for r in all_rows]
    md.append("")
    for tier in shown:
        md += [f"### {tier.capitalize()} tier", "", window_line(per_task), "",
               "Score: the dashboard tier score, against the fleet's rates on this tier; "
               "100 is the fleet average. Shown for the record; tier tables don't count toward the Implementer MVP.", "",
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
        md += [f"### {title}", "", window_line(card), "",
               f"Shown without points toward the Implementer MVP: {SCORE_NOTE}.", "",
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
                        "pilots": pilots["min_support"], "tier_tasks": MIN_TASKS, "tier_models": MIN_MODELS},
        "fleet_average": {"implementers": rows["fleet_average"], "reviewers": reviewers["fleet_average"],
                          "pilots": pilots["fleet_average"]},
        "reviews_provisional": prov, "reviews_settled": settled,
        "reviewer_window": {"window": a.reviewer_window, "since": reviewers["since"],
                            "computed_at": reviewers["computed_at"]},
        "windows": {name: {"since": utc(card["since"]), "until": utc(card["computed_at"])}
                    for name, card in (("implementers", rows), ("tiers", per_task),
                                       ("reviewers", reviewers), ("pilots", pilots))},
        "fallback_crew": a.fallback_crew,
        "implementer_mvp": {"phase": 1, "k": c["k"], "field": c["field"], "qualified": c["qualified"],
                  "winners": c["winners"],
                  "k_sensitivity": {str(k): v for k, v in c["k_sensitivity"].items()},
                  "table": crown_rows},
        "tiers_shown": shown,
        "tiers_omitted": {t: [r["crew"] for r in per_tier[t]] for t in TIERS if t not in shown},
        "ranked": {"all_tiers": len(all_rows), "reviewers": len(rev_rows), "pilots": len(pil_rows),
                   **{t: len(per_tier[t]) for t in shown}},
        "models": sorted({(r["crew"], r["model"]) for r in all_rows + tier_rows + rev_rows + pil_rows}),
        "writer": writer,
    }
    (out / "facts.json").write_text(json.dumps(facts, indent=2) + "\n")

    if a.archive:
        arch = pathlib.Path(a.archive)
        arch.mkdir(parents=True, exist_ok=True)
        # The per-task export is cut to the fields this script reads: task ids,
        # tags and context paths aren't needed to reproduce the note.
        slim = {k: v for k, v in per_task.items() if k != "tasks"}
        slim["tasks"] = [{k: t[k] for k in ("crew", "model", "tier", "counts")} for t in per_task["tasks"]]
        for name, payload in (("per-task.json", slim), ("by-type.json", by_type), ("rows.json", rows),
                              ("reviewers.json", reviewers), ("pilots.json", pilots),
                              ("facts.json", facts)):
            (arch / name).write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
