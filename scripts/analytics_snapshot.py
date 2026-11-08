#!/usr/bin/env python3
"""Write the public analytics snapshot for constellation-works.com.

Run on the Orbit owner host (the machine that holds the ``orbit`` workspace
and the local dashboard). The site renders only the JSON this script writes
under ``data/analytics/<YYYY-MM-DD>/``. Nothing in the site calls an Orbit host.

    python3 scripts/analytics_snapshot.py --out data/analytics/<YYYY-MM-DD>
    python3 scripts/analytics_snapshot.py --from data/analytics/<YYYY-MM-DD>/raw \
        --out data/analytics/<YYYY-MM-DD>

``--from`` reads ``bundle.json`` (the projected sources saved beside the
public files) and rewrites the public JSON. It does not call Orbit. A replay
of the bundle just written matches the public files byte for byte.

Windows are 30 days. Scorecards are implementers, reviewers and pilots.
Orchestrators are not requested. The trailing reviewer board is always
labelled provisional. When ``orbit agents scorecard --help`` offers
``--until`` (Orbit 0.47.0, ORB-23066), a second reviewer board is the 30
days that ended 30 days ago and is labelled settled.

Each public file is assembled by copying the field lists below. Rows whose
model is ``model unknown`` or whose crew is ``crew unknown`` or
``crew unavailable`` are dropped. Diff and friction use the sentinel crew
``unknown`` for a missing crew; those rows are dropped the same way. The
dropped count for each board is ``meta.json``'s ``dropped`` object.

Sources, by public field
------------------------
Scorecards (``scorecards.json``), CLI ``orbit --workspace <name> agents
scorecard --json``:

- implementers, reviewers, pilots: ``--role <role> --window 30d``
- implementers by tier: the same implementer command with ``--by-type``
- reviewers settled: ``--role reviewers --window 30d --until 30d`` when the
  installed binary lists ``--until``

Copied from each scorecard: ``role``, ``since``, ``until`` (else
``computed_at``), ``window``, ``min_support``, ``unit``, ``fleet_average``,
``tasks_scanned``, ``provisional`` (the count of still-provisional units),
``terms`` (``key``, ``label``, ``weight``, ``group``) and rows. A row copies
``crew``, ``model``, ``units``, ``unit``, ``score``, ``raw``, ``score_base``,
``rank`` (null while under ``min_support``, ``below_support`` or
``unjudged``), ``counts``, ``expected``, ``per_100``, ``term_units``,
``reviewed_units``, ``runs_without_model``, ``provisional``,
``provisional_terms``, ``stats`` (``key``, ``label``, ``value``) and a usage
sum from that row's ``effort_breakdown`` (invocations, duration, tokens,
cost, reasoning efforts). By-tier cells copy ``tier``, ``type``, ``crew``,
``model``, ``n``, ``units``, ``score``, ``raw``, ``crew_mean`` and a rank
within the tier and type once ``n`` reaches ``min_support``.

Metrics (``metrics.json``), the local dashboard, workspace query
``workspace=<id>`` of the named workspace. Same paths the Metrics view
fetches for ``#analytics/metrics?window=30d&outcome=succeeded``:

- durations: ``GET /api/diagnostics/implement_one?since=30d&outcome=succeeded``
  (buckets, current, previous, actors, per-complexity actors). The
  per-run ``slowest`` list is not copied; it carries task ids.
- completions: ``GET /api/diagnostics/completions?since=30d``
- defects: ``GET /api/diagnostics/defects?since=30d``
- tokens: ``GET /api/diagnostics/task_tokens?since=30d&outcome=done&scope=all``
  (the tokens tab's own default; the duration panel is the succeeded filter)
- turns: ``GET /api/diagnostics/turns_to_edit?since=30d&outcome=done``
- lines: ``GET /api/diagnostics/diff_stats?since=30d``
- friction and cost: ``GET /api/diagnostics/delivery_friction?since=30d``
  with families ``step_recovery,final_recovery,auto_fix,merge_conflict,
  failed_ci,cost``
- outcome mix: ``GET /api/tasks/completion-by-complexity`` (not windowed;
  stored as ``scope: all_time``)

Reliability (``reliability.json``): ``GET /api/metrics/reliability?window=30d``,
which is fleet-wide. Copied: the window, fleet totals (outcome counts and
the two recovery rates), outcome counts summed across workspaces by time
bucket, by job id and by activity role, and the count of unreadable
workspaces. Workspace ids, workspace names and error text are not copied.

Experiments (``experiments.json``): ``orbit experiment list --json`` and, for
each experiment whose ``status`` is ``concluded``, ``orbit experiment readout
--json <id>``. Running, paused, draft and abandoned experiments are counted
in ``dropped.experiments_omitted`` and left out. Copied: identity (id, name,
hypothesis, primary metric, concluded arm, mode, sample bounds, times),
arms (weight, n, segments, crew mix, usage), enrollment counts, per-metric
arm outcomes and intervals, differences versus control, guardrail estimates,
sample-ratio headline, lagging counts, verdict, and warning kinds without
their messages. Salts, overlays, assignment digests and run digests are not
copied. Free text (hypothesis, name, verdict reasons and labels) is copied
only after task ids, run ids, absolute paths, host names and workspace ids
(``ws_…``) are replaced with ``[redacted]``.

``meta.json`` records ``schema_version``, ``generated_at``, ``orbit_version``,
the workspace name, each board's UTC window, and ``dropped``.
"""

import argparse
import collections
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

SCHEMA_VERSION = 1
WINDOW = "30d"
SETTLED_UNTIL = "30d"
MIN_SUPPORT_DEFAULT = 10
MIN_CONFIDENT_SAMPLE = 20
PUBLIC_KEYS = ("scorecards", "metrics", "reliability", "experiments", "meta")
ROLES = ("implementers", "reviewers", "pilots")
GAP_CREWS = {"crew unknown", "crew unavailable", "unknown"}
GAP_MODELS = {"model unknown"}
TIER_ORDER = ("low", "medium", "hard", "xhard")
DEFECT_LINEAGES = ("fix_for_fix", "regression", "unattributed")
DEFECT_ORIGINS = (
    "code-review",
    "full-code-review",
    "delivery-code-review",
    "qa-sweep",
    "qa-full-sweep",
    "security-review",
    "ci-failure-sweep",
    "scanning-sweep",
    "review-reconciliation",
    "friction-curation",
    "other",
)
DIFF_MEASURES = (
    "code_added",
    "code_deleted",
    "tests_added",
    "tests_deleted",
    "other_added",
    "other_deleted",
    "net",
)
FRICTION_FAMILIES = (
    "step_recovery",
    "final_recovery",
    "auto_fix",
    "merge_conflict",
    "failed_ci",
    "cost",
)
FRICTION_PARTS = (
    "recovered",
    "failed",
    "resume",
    "settled",
    "escalated",
    "other",
    "failed_checks",
    "conflict",
    "landing_review",
    "pr_head",
    "sweep_filing",
    "invocations",
)
OUTCOME_COUNTS = (
    "total",
    "succeeded",
    "failed",
    "cascaded",
    "upgrade_paused",
    "cancelled",
    "skipped",
    "held",
    "in_flight",
    "unknown",
)
TOKEN_CELL = (
    "n",
    "sum",
    "mean",
    "median",
    "thin",
    "excluded_uncovered",
    "excluded_no_invocations",
)
TURNS_CELL = (
    "n",
    "mean_turns",
    "median_turns",
    "mean_result_bytes",
    "median_result_bytes",
    "thin",
    "excluded_no_edit",
    "excluded_empty_trace",
    "excluded_incomplete_trace",
    "excluded_no_detectable_edit",
    "excluded_no_invocation",
    "tasks",
)
TURNS_COVERAGE = (
    "tasks",
    "measured",
    "empty_trace",
    "incomplete_trace",
    "no_detectable_edit",
    "no_invocation",
    "trace_rate",
    "measured_rate",
)
COMPLETION_DONE = ("total", "low", "medium", "hard", "other")
FAILURE_RATE_LABEL = (
    "settled deliveries (success + one count per failed delivery; "
    "wrapper echoes rolled into the leaf)"
)

SAFE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_@.+-]{1,80}$")
SAFE_LABEL = re.compile(r"^[A-Za-z0-9 .,'()%/+-]{1,180}$")
SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
TIMESTAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z$")
TASK_ID = re.compile(r"ORB-[0-9]+")
RUN_ID = re.compile(r"jrun-[0-9A-Za-z-]+")
ABS_PATH = re.compile(r"/(?:home|Users|tmp|var|opt|etc|usr|private)/[^\s\"']*")
HOME_PATH = re.compile(r"(?:^|\s)~/[^\s\"']*")
WORKSPACE_ID = re.compile(r"\bws_[A-Za-z0-9_-]+\b")


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_gap_crew(crew):
    return isinstance(crew, str) and crew in GAP_CREWS


def is_gap_model(model):
    return isinstance(model, str) and model in GAP_MODELS


def is_gap_actor(actor):
    if not isinstance(actor, str):
        return False
    if is_gap_crew(actor) or is_gap_model(actor):
        return True
    if " / " in actor:
        crew, model = actor.split(" / ", 1)
        return is_gap_crew(crew) or is_gap_model(model)
    return False


def numeric_map(obj):
    """Copy a map whose keys are snake_case and whose values are numbers or null."""
    if not isinstance(obj, dict):
        return None
    out = {}
    for key, value in obj.items():
        if not isinstance(key, str) or not SAFE_KEY.fullmatch(key):
            continue
        if value is None or is_number(value):
            out[key] = value
    return out


def whole(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def dump(obj):
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def host_names():
    names = {"dk-server-1", "dk-server-2"}
    for probe in (socket.gethostname, socket.getfqdn):
        try:
            found = probe()
        except OSError:
            continue
        if found and found not in ("localhost", "localhost.localdomain"):
            names.add(found)
    return sorted(names)


def forbidden_patterns(hosts):
    patterns = [TASK_ID, RUN_ID, ABS_PATH, HOME_PATH, WORKSPACE_ID]
    for host in hosts:
        if len(host) >= 3:
            patterns.append(re.compile(re.escape(host)))
    return patterns


def sanitize(text, patterns, redactions):
    if not isinstance(text, str) or not text:
        return text
    out = text
    for pattern in patterns:
        out, count = pattern.subn("[redacted]", out)
        redactions[0] += count
    return out


def scan(obj, patterns, path="$"):
    if isinstance(obj, dict):
        for key, value in obj.items():
            scan(key, patterns, path + "." + str(key))
            scan(value, patterns, path + "." + str(key))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            scan(value, patterns, f"{path}[{index}]")
    elif isinstance(obj, str):
        for pattern in patterns:
            if pattern.search(obj):
                raise SystemExit(f"forbidden pattern {pattern.pattern} in output at {path}")


def assert_no_gap_values(obj, path="$"):
    if isinstance(obj, dict):
        if is_gap_crew(obj.get("crew")) or is_gap_model(obj.get("model")) or is_gap_actor(obj.get("actor")):
            raise SystemExit(f"attribution-gap row survived at {path}")
        crews = obj.get("crews")
        if isinstance(crews, list) and any(is_gap_crew(crew) for crew in crews if isinstance(crew, str)):
            raise SystemExit(f"attribution-gap crew survived at {path}.crews")
        for key, value in obj.items():
            assert_no_gap_values(value, path + "." + str(key))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            assert_no_gap_values(value, f"{path}[{index}]")


def orbit_json(args, workspace=None, timeout=600):
    cmd = ["orbit"]
    if workspace:
        cmd.extend(["--workspace", workspace])
    cmd.extend([*args, "--json"])
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else exc.returncode
        raise SystemExit(f"orbit {' '.join(args)} failed ({tail})") from exc
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(f"orbit {' '.join(args)} timed out") from exc
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"orbit {' '.join(args)} did not return JSON") from exc


def orbit_version():
    proc = subprocess.run(["orbit", "--version"], check=True, capture_output=True, text=True, timeout=30)
    parts = proc.stdout.strip().split()
    return parts[-1] if parts else proc.stdout.strip()


def scorecard_supports_until():
    proc = subprocess.run(
        ["orbit", "agents", "scorecard", "--help"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return "--until" in proc.stdout


def workspace_id(name):
    listed = orbit_json(["workspace", "list"])
    if not isinstance(listed, list):
        raise SystemExit("orbit workspace list did not return a list")
    for entry in listed:
        if isinstance(entry, dict) and entry.get("name") == name and entry.get("status") == "active":
            ident = entry.get("id")
            if isinstance(ident, str) and ident:
                return ident
    raise SystemExit(f"no active workspace named {name}")


def check_dashboard(url):
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    if parsed.scheme != "http" or host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("dashboard URL must be loopback http (127.0.0.1, localhost or ::1)")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SystemExit("dashboard URL must be a bare loopback origin")
    return url.rstrip("/")


def http_json(base, path, query):
    url = base + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"dashboard {path} returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"dashboard {path} was unreachable ({exc.reason})") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"dashboard {path} did not return JSON") from exc


def project_terms(terms):
    out = []
    if not isinstance(terms, list):
        return out
    for term in terms:
        if not isinstance(term, dict):
            continue
        key, label, weight = term.get("key"), term.get("label"), term.get("weight")
        if not isinstance(key, str) or not SAFE_KEY.fullmatch(key):
            continue
        if not isinstance(label, str) or not SAFE_LABEL.fullmatch(label):
            continue
        if not is_number(weight):
            continue
        item = {"key": key, "label": label, "weight": weight}
        group = term.get("group")
        if isinstance(group, str) and SAFE_KEY.fullmatch(group):
            item["group"] = group
        out.append(item)
    return out


def score_key(terms, unit, fleet_average):
    credit = [term["label"].lower() for term in terms if term["weight"] > 0]
    debit = [term["label"].lower() for term in terms if term["weight"] < 0]
    credit_text = ", ".join(credit) if credit else "none"
    debit_text = ", ".join(debit) if debit else "none"
    return (
        f"Score: per 100 {unit}, credit for {credit_text}; "
        f"debits for {debit_text}. The fleet average is {fleet_average:.1f}."
    )


def project_stats(stats):
    if not isinstance(stats, list):
        return None
    out = []
    for item in stats:
        if not isinstance(item, dict):
            continue
        key, label, value = item.get("key"), item.get("label"), item.get("value")
        if not isinstance(key, str) or not SAFE_KEY.fullmatch(key):
            continue
        if not isinstance(label, str) or not SAFE_LABEL.fullmatch(label):
            continue
        if value is not None and not is_number(value) and not isinstance(value, bool):
            continue
        out.append({"key": key, "label": label, "value": value})
    return out


def project_string_list(values):
    if not isinstance(values, list):
        return None
    out = []
    for value in values:
        if not isinstance(value, str) or not SAFE_KEY.fullmatch(value):
            return None
        out.append(value)
    return out


def project_usage(breakdown, dropped, board):
    if not isinstance(breakdown, list) or not breakdown:
        return None
    totals = {
        "invocations": 0,
        "duration_ms": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "provider_cost_count": 0,
    }
    cost = 0.0
    efforts = collections.Counter()
    kept = 0
    for entry in breakdown:
        if not isinstance(entry, dict):
            continue
        if is_gap_crew(entry.get("crew")) or is_gap_model(entry.get("model")):
            dropped[board] += 1
            continue
        kept += 1
        for key in totals:
            amount = whole(entry.get(key))
            if amount is not None:
                totals[key] += amount
        if is_number(entry.get("provider_cost_usd")):
            cost += entry["provider_cost_usd"]
        effort = entry.get("reasoning_effort")
        if isinstance(effort, str) and effort not in ("", "unknown") and SAFE_TOKEN.fullmatch(effort):
            efforts[effort] += whole(entry.get("invocations")) or 1
    if not kept:
        return None
    totals["provider_cost_usd"] = cost
    totals["efforts"] = ", ".join(name for name, _count in efforts.most_common())
    return totals


def project_row(row, min_support, unit, dropped, board):
    if not isinstance(row, dict):
        return None
    crew, model = row.get("crew"), row.get("model")
    if is_gap_crew(crew) or is_gap_model(model):
        dropped[board] += 1
        return None
    if not isinstance(crew, str) or not SAFE_TOKEN.fullmatch(crew):
        return None
    if not isinstance(model, str) or not SAFE_TOKEN.fullmatch(model):
        return None
    units = row.get("units")
    if not is_number(units):
        return None
    below = bool(row.get("below_support")) or bool(row.get("unjudged")) or units < min_support
    rank = row.get("rank")
    if below or isinstance(rank, bool) or not isinstance(rank, int):
        rank = None
    projected = {
        "below_support": below,
        "crew": crew,
        "model": model,
        "rank": rank,
        "unit": unit,
        "units": units,
        "unjudged": bool(row.get("unjudged")),
    }
    for key in ("raw", "score", "score_base"):
        if is_number(row.get(key)):
            projected[key] = row[key]
    for key in ("counts", "expected", "per_100", "term_units"):
        copied = numeric_map(row.get(key))
        if copied is not None and key in row:
            projected[key] = copied
    reviewed = row.get("reviewed_units")
    if is_number(reviewed):
        projected["reviewed_units"] = reviewed
    runs_without = row.get("runs_without_model")
    if is_number(runs_without):
        projected["runs_without_model"] = runs_without
    provisional = row.get("provisional")
    if is_number(provisional):
        projected["provisional"] = provisional
    terms = project_string_list(row.get("provisional_terms"))
    if terms is not None and "provisional_terms" in row:
        projected["provisional_terms"] = terms
    stats = project_stats(row.get("stats"))
    if stats is not None and "stats" in row:
        projected["stats"] = stats
    usage = project_usage(row.get("effort_breakdown"), dropped, board)
    if usage is not None:
        projected["usage"] = usage
    return projected


def window_of(card):
    since = card.get("since") if isinstance(card.get("since"), str) else None
    until = card.get("until") if isinstance(card.get("until"), str) else None
    if until is None and isinstance(card.get("computed_at"), str):
        until = card["computed_at"]
    key = card.get("window") if isinstance(card.get("window"), str) else card.get("requested_window")
    return {"key": key, "since": since, "until": until}


def project_board(card, provisional, dropped, board, settled=False):
    min_support = card.get("min_support")
    if isinstance(min_support, bool) or not isinstance(min_support, int):
        min_support = MIN_SUPPORT_DEFAULT
    unit = card.get("unit") if isinstance(card.get("unit"), str) and SAFE_LABEL.fullmatch(card["unit"]) else "units"
    fleet = card.get("fleet_average") if is_number(card.get("fleet_average")) else None
    terms = project_terms(card.get("terms"))
    rows = []
    for row in card.get("rows") or []:
        projected = project_row(row, min_support, unit, dropped, board)
        if projected is not None:
            rows.append(projected)
    role = card.get("role") if card.get("role") in ROLES else board.split("_", 1)[0]
    projected = {
        "fleet_average": fleet,
        "min_support": min_support,
        "provisional": provisional,
        "role": role,
        "rows": rows,
        "score_key": score_key(terms, unit, fleet) if fleet is not None else None,
        "settled": settled,
        "terms": terms,
        "unit": unit,
        "window": window_of(card),
    }
    scanned = card.get("tasks_scanned")
    if isinstance(scanned, int) and not isinstance(scanned, bool):
        projected["tasks_scanned"] = scanned
    provisional_units = card.get("provisional")
    if isinstance(provisional_units, int) and not isinstance(provisional_units, bool):
        projected["provisional_units"] = provisional_units
    return projected


def project_cells(card, dropped):
    min_support = card.get("min_support")
    if isinstance(min_support, bool) or not isinstance(min_support, int):
        min_support = MIN_SUPPORT_DEFAULT
    cells = []
    for cell in card.get("cells") or []:
        if not isinstance(cell, dict):
            continue
        crew, model, count = cell.get("crew"), cell.get("model"), cell.get("n")
        if not is_number(count) or count <= 0:
            continue
        if is_gap_crew(crew) or is_gap_model(model):
            dropped["implementers_by_tier"] += 1
            continue
        tier, kind = cell.get("tier"), cell.get("type")
        if tier not in TIER_ORDER or not isinstance(kind, str) or not SAFE_KEY.fullmatch(kind):
            continue
        if not isinstance(crew, str) or not SAFE_TOKEN.fullmatch(crew):
            continue
        if not isinstance(model, str) or not SAFE_TOKEN.fullmatch(model):
            continue
        item = {
            "below_support": count < min_support,
            "crew": crew,
            "model": model,
            "n": count,
            "rank": None,
            "tier": tier,
            "type": kind,
            "unit": "tasks",
            "units": count,
        }
        for key in ("crew_mean", "raw", "score"):
            if is_number(cell.get(key)):
                item[key] = cell[key]
        cells.append(item)
    grouped = collections.defaultdict(list)
    for cell in cells:
        if not cell["below_support"]:
            grouped[(cell["tier"], cell["type"])].append(cell)
    for group in grouped.values():
        group.sort(key=lambda cell: (-cell.get("crew_mean", cell.get("score", 0)), cell["crew"], cell["model"]))
        for index, cell in enumerate(group, 1):
            cell["rank"] = index
    cells.sort(key=lambda cell: (
        TIER_ORDER.index(cell["tier"]),
        cell["type"],
        cell["rank"] is None,
        cell["rank"] or 0,
        cell["crew"],
        cell["model"],
    ))
    return {
        "cells": cells,
        "min_support": min_support,
        "provisional": False,
        "role": "implementers",
        "settled": False,
        "unit": "tasks",
        "window": window_of(card),
    }


def trend_window(window):
    if not isinstance(window, dict):
        return None
    out = {}
    for key in ("key", "since", "until", "previous_since", "previous_until"):
        value = window.get(key)
        if isinstance(value, str) and (key == "key" or TIMESTAMP.fullmatch(value[:20] + "Z") or "T" in value):
            out[key] = value
        elif value is None and key in window:
            out[key] = None
    for key in ("bucket_seconds", "lead_buckets"):
        if isinstance(window.get(key), int) and not isinstance(window.get(key), bool):
            out[key] = window[key]
    return out


def duration_stats(obj):
    if obj is None:
        return None
    if not isinstance(obj, dict):
        return None
    out = {}
    for key in ("n", "avg", "p50", "p95"):
        if is_number(obj.get(key)):
            out[key] = obj[key]
    return out or None


def project_actor(row, dropped, board):
    if not isinstance(row, dict):
        return None
    actor = row.get("actor")
    if is_gap_actor(actor):
        dropped[board] += 1
        return None
    if not isinstance(actor, str) or not re.fullmatch(r"[A-Za-z0-9_@ .+/-]{1,120}", actor):
        return None
    projected = duration_stats(row) or {}
    projected["actor"] = actor
    if "previous_avg" in row and (row["previous_avg"] is None or is_number(row["previous_avg"])):
        projected["previous_avg"] = row["previous_avg"]
    trend = row.get("trend")
    if isinstance(trend, list) and all(item is None or is_number(item) for item in trend):
        projected["trend"] = trend
    return projected


def project_duration_series(obj):
    if not isinstance(obj, dict):
        return None
    out = {}
    for key in ("all", "low", "medium", "hard", "xhard", "unset"):
        if key in obj:
            out[key] = duration_stats(obj[key])
    return out


def project_durations(payload, dropped):
    buckets = []
    for bucket in payload.get("buckets") or []:
        if not isinstance(bucket, dict):
            continue
        item = {}
        if isinstance(bucket.get("start"), str):
            item["start"] = bucket["start"]
        if is_number(bucket.get("other_runs")):
            item["other_runs"] = bucket["other_runs"]
        for key in ("all", "low", "medium", "hard"):
            if key in bucket:
                item[key] = duration_stats(bucket[key])
        buckets.append(item)
    actors = []
    for row in payload.get("actors") or []:
        projected = project_actor(row, dropped, "metrics_durations")
        if projected is not None:
            actors.append(projected)
    by_complexity = []
    for group in payload.get("implement_one_by_complexity") or []:
        if not isinstance(group, dict):
            continue
        complexity = group.get("complexity")
        if not isinstance(complexity, str) or not SAFE_KEY.fullmatch(complexity):
            continue
        group_actors = []
        for row in group.get("actors") or []:
            projected = project_actor(row, dropped, "metrics_durations")
            if projected is not None:
                group_actors.append(projected)
        by_complexity.append({
            "actors": group_actors,
            "complexity": complexity,
            "n": whole(group.get("n")) or 0,
        })
    return {
        "actors": actors,
        "buckets": buckets,
        "current": project_duration_series(payload.get("current")),
        "implement_one_by_complexity": by_complexity,
        "outcome": "succeeded" if payload.get("outcome") == "succeeded" else None,
        "previous": project_duration_series(payload.get("previous")) if payload.get("previous") is not None else None,
        "source": "GET /api/diagnostics/implement_one?since=30d&outcome=succeeded",
        "truncated": bool(payload.get("truncated")),
        "window": trend_window(payload.get("window")),
    }


def project_completion_counts(obj):
    if not isinstance(obj, dict):
        return None
    done = obj.get("done") if isinstance(obj.get("done"), dict) else {}
    return {
        "archived": whole(obj.get("archived")) or 0,
        "done": {key: whole(done.get(key)) or 0 for key in COMPLETION_DONE},
        "rejected": whole(obj.get("rejected")) or 0,
    }


def project_completions(payload):
    def buckets(rows):
        out = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            item = project_completion_counts(row)
            if isinstance(row.get("start"), str):
                item["start"] = row["start"]
            out.append(item)
        return out

    return {
        "buckets": buckets(payload.get("buckets")),
        "current": project_completion_counts(payload.get("current")),
        "lead_buckets": [project_completion_counts(row) for row in payload.get("lead_buckets") or []],
        "previous": project_completion_counts(payload.get("previous")) if payload.get("previous") is not None else None,
        "previous_undated": project_completion_counts(payload.get("previous_undated"))
        if payload.get("previous_undated") is not None else None,
        "source": "GET /api/diagnostics/completions?since=30d",
        "undated": project_completion_counts(payload.get("undated")),
        "window": trend_window(payload.get("window")),
    }


def project_defect_counts(obj):
    if not isinstance(obj, dict):
        return None
    lineage = obj.get("lineage") if isinstance(obj.get("lineage"), dict) else {}
    origin = obj.get("origin") if isinstance(obj.get("origin"), dict) else {}
    return {
        "lineage": {key: whole(lineage.get(key)) or 0 for key in DEFECT_LINEAGES},
        "origin": {key: whole(origin.get(key)) or 0 for key in DEFECT_ORIGINS},
        "total": whole(obj.get("total")) or 0,
    }


def project_defects(payload):
    buckets = []
    for row in payload.get("buckets") or []:
        if not isinstance(row, dict):
            continue
        item = project_defect_counts(row)
        if isinstance(row.get("start"), str):
            item["start"] = row["start"]
        buckets.append(item)
    return {
        "buckets": buckets,
        "current": project_defect_counts(payload.get("current")),
        "lead_buckets": [project_defect_counts(row) for row in payload.get("lead_buckets") or []],
        "lineages": list(DEFECT_LINEAGES),
        "origins": list(DEFECT_ORIGINS),
        "previous": project_defect_counts(payload.get("previous")) if payload.get("previous") is not None else None,
        "source": "GET /api/diagnostics/defects?since=30d",
        "window": trend_window(payload.get("window")),
    }


def project_number_cell(obj, fields):
    if not isinstance(obj, dict):
        return None
    out = {}
    for key in fields:
        value = obj.get(key)
        if isinstance(value, bool) or value is None or is_number(value):
            if key in obj:
                out[key] = value
    return out


def project_token_series(series):
    if not isinstance(series, dict):
        return None
    complexity, cohort = series.get("complexity"), series.get("cohort")
    if not isinstance(complexity, str) or not SAFE_KEY.fullmatch(complexity):
        return None
    if cohort not in ("all", "with", "without"):
        return None
    return {
        "cohort": cohort,
        "complexity": complexity,
        "lead_points": [project_number_cell(point, TOKEN_CELL) for point in series.get("lead_points") or []],
        "points": [project_number_cell(point, TOKEN_CELL) for point in series.get("points") or []],
        "total": project_number_cell(series.get("total"), TOKEN_CELL),
    }


def project_tokens(payload, dropped):
    models = []
    for row in payload.get("available_models") or []:
        if not isinstance(row, dict):
            continue
        model, tasks = row.get("model"), row.get("tasks")
        if is_gap_model(model):
            dropped["metrics_tokens"] += 1
            continue
        if not isinstance(model, str) or not SAFE_TOKEN.fullmatch(model) or not is_number(tasks):
            continue
        models.append({"model": model, "tasks": tasks})
    return {
        "available_models": models,
        "bucket_starts": [item for item in payload.get("bucket_starts") or [] if isinstance(item, str)],
        "excluded_other_model": whole(payload.get("excluded_other_model")) or 0,
        "min_tasks": whole(payload.get("min_tasks")),
        "outcome": payload.get("outcome") if payload.get("outcome") in ("done", "all") else None,
        "scope": payload.get("scope") if payload.get("scope") in ("all", "implement") else None,
        "series": [item for item in (project_token_series(series) for series in payload.get("series") or []) if item],
        "source": "GET /api/diagnostics/task_tokens?since=30d&outcome=done&scope=all",
        "total": project_number_cell(payload.get("total"), TOKEN_CELL),
        "undated_tasks": whole(payload.get("undated_tasks")) or 0,
        "window": trend_window(payload.get("window")),
    }


def project_turns(payload):
    def series_of(series):
        if not isinstance(series, dict):
            return None
        complexity, cohort = series.get("complexity"), series.get("cohort")
        if not isinstance(complexity, str) or not SAFE_KEY.fullmatch(complexity):
            return None
        if cohort not in ("all", "with", "without"):
            return None
        return {
            "cohort": cohort,
            "complexity": complexity,
            "points": [project_number_cell(point, TURNS_CELL) for point in series.get("points") or []],
            "total": project_number_cell(series.get("total"), TURNS_CELL),
        }

    providers = []
    for row in payload.get("available_providers") or []:
        if not isinstance(row, dict):
            continue
        provider = row.get("provider")
        if not isinstance(provider, str) or not SAFE_TOKEN.fullmatch(provider):
            continue
        providers.append({
            "coverage": project_number_cell(row, TURNS_COVERAGE),
            "provider": provider,
        })
    return {
        "available_providers": providers,
        "bucket_starts": [item for item in payload.get("bucket_starts") or [] if isinstance(item, str)],
        "coverage": project_number_cell(payload.get("coverage"), TURNS_COVERAGE),
        "excluded_other_provider": whole(payload.get("excluded_other_provider")) or 0,
        "min_tasks": whole(payload.get("min_tasks")),
        "outcome": payload.get("outcome") if payload.get("outcome") in ("done", "all") else None,
        "series": [item for item in (series_of(series) for series in payload.get("series") or []) if item],
        "source": "GET /api/diagnostics/turns_to_edit?since=30d&outcome=done",
        "total": project_number_cell(payload.get("total"), TURNS_CELL),
        "truncated": bool(payload.get("truncated")),
        "undated_tasks": whole(payload.get("undated_tasks")) or 0,
        "window": trend_window(payload.get("window")),
    }


def project_diff_cell(obj):
    if not isinstance(obj, dict):
        return None
    return {
        "mean": numeric_map(obj.get("mean")) or {},
        "median": numeric_map(obj.get("median")) or {},
        "n": whole(obj.get("n")) or 0,
        "sum": numeric_map(obj.get("sum")) or {},
        "thin": bool(obj.get("thin")),
    }


def project_diff_series(series, dropped):
    if not isinstance(series, dict):
        return None
    key = series.get("key")
    names = [crew for crew in series.get("crews") or [] if isinstance(crew, str)]
    gap_names = [crew for crew in names if is_gap_crew(crew)]
    dropped["metrics_diff"] += len(gap_names)
    if is_gap_crew(key):
        dropped["metrics_diff"] += 1
        return None
    if not isinstance(key, str) or not SAFE_TOKEN.fullmatch(key):
        return None
    kept = [crew for crew in names if isinstance(crew, str) and SAFE_TOKEN.fullmatch(crew) and not is_gap_crew(crew)]
    return {
        "crews": kept,
        "key": key,
        "lead_points": [project_diff_cell(point) for point in series.get("lead_points") or []],
        "points": [project_diff_cell(point) for point in series.get("points") or []],
        "total": project_diff_cell(series.get("total")),
    }


def project_diff(payload, dropped):
    complexities = []
    for row in payload.get("available_complexities") or []:
        if not isinstance(row, dict):
            continue
        complexity, deliveries = row.get("complexity"), row.get("deliveries")
        if isinstance(complexity, str) and SAFE_KEY.fullmatch(complexity) and is_number(deliveries):
            complexities.append({"complexity": complexity, "deliveries": deliveries})
    return {
        "available_complexities": complexities,
        "bucket_starts": [item for item in payload.get("bucket_starts") or [] if isinstance(item, str)],
        "crews": [item for item in (project_diff_series(series, dropped) for series in payload.get("crews") or []) if item],
        "measures": [item for item in payload.get("measures") or [] if item in DIFF_MEASURES],
        "min_deliveries": whole(payload.get("min_deliveries")),
        "overall": project_diff_series(payload.get("overall"), dropped),
        "source": "GET /api/diagnostics/diff_stats?since=30d",
        "window": trend_window(payload.get("window")),
    }


def project_friction_cell(obj):
    if not isinstance(obj, dict):
        return None
    breakdown = obj.get("breakdown") if isinstance(obj.get("breakdown"), dict) else {}
    projected = {
        "breakdown": {key: breakdown[key] for key in FRICTION_PARTS if is_number(breakdown.get(key))},
        "count": obj.get("count") if is_number(obj.get("count")) else 0,
        "denominator": whole(obj.get("denominator")) or 0,
        "rate": obj.get("rate") if (obj.get("rate") is None or is_number(obj.get("rate"))) else None,
        "sparse": bool(obj.get("sparse")),
    }
    if is_number(obj.get("excluded_invocations")):
        projected["excluded_invocations"] = obj["excluded_invocations"]
    return projected


def project_friction(payload, dropped):
    families = []
    for family in payload.get("families") or []:
        if not isinstance(family, dict) or family.get("family") not in FRICTION_FAMILIES:
            continue
        label, unit = family.get("label"), family.get("unit")
        families.append({
            "family": family["family"],
            "filtered": bool(family.get("filtered")),
            "label": label if isinstance(label, str) and SAFE_LABEL.fullmatch(label) else family["family"],
            "points": [project_friction_cell(point) for point in family.get("points") or []],
            "previous": project_friction_cell(family.get("previous")) if family.get("previous") is not None else None,
            "task_scoped": bool(family.get("task_scoped")),
            "total": project_friction_cell(family.get("total")),
            "unit": unit if isinstance(unit, str) and SAFE_TOKEN.fullmatch(unit) else "events",
        })
    crews = []
    for row in payload.get("available_crews") or []:
        if not isinstance(row, dict):
            continue
        crew, tasks = row.get("crew"), row.get("tasks")
        if is_gap_crew(crew):
            dropped["metrics_friction"] += 1
            continue
        if isinstance(crew, str) and SAFE_TOKEN.fullmatch(crew) and is_number(tasks):
            crews.append({"crew": crew, "tasks": tasks})
    complexities = []
    for row in payload.get("available_complexities") or []:
        if not isinstance(row, dict):
            continue
        complexity, tasks = row.get("complexity"), row.get("tasks")
        if isinstance(complexity, str) and SAFE_KEY.fullmatch(complexity) and is_number(tasks):
            complexities.append({"complexity": complexity, "tasks": tasks})
    done = payload.get("done") if isinstance(payload.get("done"), dict) else {}

    def count_list(key):
        values = done.get(key)
        if isinstance(values, list) and all(is_number(item) for item in values):
            return values
        if is_number(values):
            return values
        return None

    return {
        "available_complexities": complexities,
        "available_crews": crews,
        "bucket_starts": [item for item in payload.get("bucket_starts") or [] if isinstance(item, str)],
        "done": {
            "points": count_list("points"),
            "previous": whole(done.get("previous")),
            "previous_undated": whole(done.get("previous_undated")),
            "total": whole(done.get("total")),
            "undated": whole(done.get("undated")),
            "unfiltered_points": count_list("unfiltered_points"),
            "unfiltered_total": whole(done.get("unfiltered_total")),
            "unfiltered_undated": whole(done.get("unfiltered_undated")),
        },
        "families": families,
        "min_done": whole(payload.get("min_done")),
        "source": (
            "GET /api/diagnostics/delivery_friction?since=30d"
            "&families=step_recovery,final_recovery,auto_fix,merge_conflict,failed_ci,cost"
        ),
        "window": trend_window(payload.get("window")),
    }


def project_outcome_mix(payload):
    rows = []
    for row in payload.get("by_complexity") or []:
        if not isinstance(row, dict):
            continue
        complexity = row.get("complexity")
        if not isinstance(complexity, str) or not SAFE_KEY.fullmatch(complexity):
            continue
        statuses = []
        for status in row.get("statuses") or []:
            if not isinstance(status, dict):
                continue
            name = status.get("status")
            if not isinstance(name, str) or not SAFE_KEY.fullmatch(name):
                continue
            statuses.append({
                "count": whole(status.get("count")) or 0,
                "rate": status.get("rate") if is_number(status.get("rate")) else None,
                "status": name,
                "total": whole(status.get("total")) or 0,
            })
        rows.append({
            "complexity": complexity,
            "statuses": statuses,
            "total": whole(row.get("total")) or 0,
        })
    return {
        "by_complexity": rows,
        "scope": "all_time",
        "source": "GET /api/tasks/completion-by-complexity",
    }


def project_counts(obj):
    source = obj if isinstance(obj, dict) else {}
    return {key: whole(source.get(key)) or 0 for key in OUTCOME_COUNTS}


def failure_rate(counts, label=FAILURE_RATE_LABEL):
    numerator = counts["failed"]
    denominator = counts["succeeded"] + counts["failed"]
    return {
        "denominator": denominator,
        "denominator_label": label,
        "low_sample": denominator < MIN_CONFIDENT_SAMPLE,
        "numerator": numerator,
        "value": None if denominator == 0 else numerator / denominator,
    }


def project_rate(obj, fallback_label):
    if not isinstance(obj, dict):
        return failure_rate({key: 0 for key in OUTCOME_COUNTS}, fallback_label)
    label = obj.get("denominator_label")
    if not isinstance(label, str) or not SAFE_LABEL.fullmatch(label):
        label = fallback_label
    numerator = whole(obj.get("numerator")) or 0
    denominator = whole(obj.get("denominator")) or 0
    value = obj.get("value")
    return {
        "denominator": denominator,
        "denominator_label": label,
        "low_sample": bool(obj.get("low_sample")),
        "numerator": numerator,
        "value": value if value is None or is_number(value) else None,
    }


def add_counts(left, right):
    return {key: left[key] + right[key] for key in OUTCOME_COUNTS}


def project_reliability(payload, dropped):
    workspaces = payload.get("workspaces") if isinstance(payload.get("workspaces"), list) else []
    by_job = {}
    by_bucket = {}
    by_activity = {}
    observed = collections.Counter()
    for workspace in workspaces:
        if not isinstance(workspace, dict):
            continue
        runs = workspace.get("job_runs") if isinstance(workspace.get("job_runs"), dict) else {}
        for row in runs.get("by_job") or []:
            if not isinstance(row, dict):
                continue
            job = row.get("job_id")
            if not isinstance(job, str) or not SAFE_TOKEN.fullmatch(job):
                dropped["reliability"] += 1
                continue
            by_job[job] = add_counts(by_job.get(job, project_counts(None)), project_counts(row.get("counts")))
        for row in runs.get("over_time") or []:
            if not isinstance(row, dict) or not isinstance(row.get("bucket_start"), str):
                continue
            start = row["bucket_start"]
            current = by_bucket.get(start)
            counts = project_counts(row.get("counts"))
            if current is None:
                by_bucket[start] = {"bucket_end": row.get("bucket_end"), "bucket_start": start, "counts": counts}
            else:
                current["counts"] = add_counts(current["counts"], counts)
        states = runs.get("observed_states")
        if isinstance(states, dict):
            for name, count in states.items():
                if isinstance(name, str) and SAFE_KEY.fullmatch(name) and is_number(count):
                    observed[name] += int(count)
        recovery = workspace.get("recovery") if isinstance(workspace.get("recovery"), dict) else {}
        for row in recovery.get("by_activity") or []:
            if not isinstance(row, dict):
                continue
            activity, role = row.get("activity_id"), row.get("role")
            if not isinstance(activity, str) or not SAFE_TOKEN.fullmatch(activity):
                dropped["reliability"] += 1
                continue
            if role not in ("step", "recovery", "ambiguous", "unknown"):
                dropped["reliability"] += 1
                continue
            slot = by_activity.setdefault((activity, role), {"invocation_count": 0, "job_run_count": 0})
            slot["invocation_count"] += whole(row.get("invocation_count")) or 0
            slot["job_run_count"] += whole(row.get("job_run_count")) or 0
    label = FAILURE_RATE_LABEL
    totals = payload.get("totals") if isinstance(payload.get("totals"), dict) else {}
    job_totals = totals.get("job_runs") if isinstance(totals.get("job_runs"), dict) else {}
    if isinstance(job_totals.get("failure_rate"), dict):
        copied = job_totals["failure_rate"].get("denominator_label")
        if isinstance(copied, str) and SAFE_LABEL.fullmatch(copied):
            label = copied
    jobs = [{
        "counts": counts,
        "failure_rate": failure_rate(counts, label),
        "job_id": job,
    } for job, counts in sorted(by_job.items(), key=lambda item: (-item[1]["failed"], -item[1]["total"], item[0]))]
    buckets = []
    for start, bucket in sorted(by_bucket.items()):
        end = bucket["bucket_end"] if isinstance(bucket["bucket_end"], str) else None
        buckets.append({
            "bucket_end": end,
            "bucket_start": start,
            "counts": bucket["counts"],
            "failure_rate": failure_rate(bucket["counts"], label),
        })
    activities = [{
        "activity_id": activity,
        "invocation_count": counts["invocation_count"],
        "job_run_count": counts["job_run_count"],
        "role": role,
    } for (activity, role), counts in sorted(by_activity.items(), key=lambda item: (-item[1]["invocation_count"], item[0]))]
    recovery = totals.get("recovery") if isinstance(totals.get("recovery"), dict) else {}
    window = payload.get("window") if isinstance(payload.get("window"), dict) else {}
    unreadable = payload.get("unreadable_workspaces")
    return {
        "activities": activities,
        "by_job": jobs,
        "observed_states": dict(sorted(observed.items())),
        "over_time": buckets,
        "scope": "fleet",
        "source": "GET /api/metrics/reliability?window=30d",
        "totals": {
            "job_runs": {
                "counts": project_counts(job_totals.get("counts")),
                "failure_rate": project_rate(job_totals.get("failure_rate"), label),
                "truncated": bool(job_totals.get("truncated")),
            },
            "recovery": {
                "per_job_run": project_rate(recovery.get("per_job_run"), "job runs with any recorded invocation"),
                "per_step_invocation": project_rate(
                    recovery.get("per_step_invocation"), "step-activity invocations"
                ),
            },
        },
        "unreadable_workspace_count": len(unreadable) if isinstance(unreadable, list) else 0,
        "window": {
            "bucket": window.get("bucket") if window.get("bucket") in ("hour", "day") else None,
            "label": window.get("label") if isinstance(window.get("label"), str) else WINDOW,
            "since": window.get("since") if isinstance(window.get("since"), str) else None,
            "until": window.get("until") if isinstance(window.get("until"), str) else None,
        },
    }


def number_list(values, size=None):
    if not isinstance(values, list) or not all(is_number(item) for item in values):
        return None
    if size is not None and len(values) != size:
        return None
    return values


def project_interval_arm(arm):
    if not isinstance(arm, dict):
        return None
    name = arm.get("arm")
    if not isinstance(name, str) or not SAFE_TOKEN.fullmatch(name):
        return None
    projected = {"arm": name}
    for key in ("mean", "median", "n", "open", "unmeasured"):
        value = arm.get(key)
        if value is None or is_number(value):
            if key in arm:
                projected[key] = value
    for key in ("mean_interval", "median_interval"):
        interval = number_list(arm.get(key), 2)
        if interval is not None:
            projected[key] = interval
    segments = []
    for segment in arm.get("segments") or []:
        if not isinstance(segment, dict) or not is_number(segment.get("segment")):
            continue
        item = {"n": whole(segment.get("n")) or 0, "segment": segment["segment"]}
        for key in ("mean", "median"):
            if is_number(segment.get(key)):
                item[key] = segment[key]
        for key in ("mean_interval", "median_interval"):
            interval = number_list(segment.get(key), 2)
            if interval is not None:
                item[key] = interval
        segments.append(item)
    if segments:
        projected["segments"] = segments
    return projected


def project_difference(diff):
    if not isinstance(diff, dict):
        return None
    name = diff.get("arm")
    if not isinstance(name, str) or not SAFE_TOKEN.fullmatch(name):
        return None
    overall = diff.get("overall") if isinstance(diff.get("overall"), dict) else {}
    dropped = overall.get("cells_dropped")
    cells = [item for item in dropped or [] if isinstance(item, str) and SAFE_KEY.fullmatch(item)] if isinstance(dropped, list) else []
    by_complexity = []
    for row in diff.get("by_complexity") or []:
        if not isinstance(row, dict):
            continue
        complexity = row.get("complexity")
        if not isinstance(complexity, str) or not SAFE_KEY.fullmatch(complexity):
            continue
        item = {
            "complexity": complexity,
            "estimate": row.get("estimate") if row.get("estimate") is None or is_number(row.get("estimate")) else None,
            "n_arm": whole(row.get("n_arm")) or 0,
            "n_control": whole(row.get("n_control")) or 0,
        }
        interval = number_list(row.get("interval"), 2)
        if interval is not None:
            item["interval"] = interval
        by_complexity.append(item)
    projected_overall = {
        "cells_dropped": cells,
        "estimate": overall.get("estimate") if overall.get("estimate") is None or is_number(overall.get("estimate")) else None,
    }
    interval = number_list(overall.get("interval"), 2)
    if interval is not None:
        projected_overall["interval"] = interval
    return {"arm": name, "by_complexity": by_complexity, "overall": projected_overall}


def project_metric(metric):
    if not isinstance(metric, dict):
        return None
    name = metric.get("metric")
    if not isinstance(name, str) or not SAFE_TOKEN.fullmatch(name):
        return None
    return {
        "arms": [item for item in (project_interval_arm(arm) for arm in metric.get("arms") or []) if item],
        "better": metric.get("better") if isinstance(metric.get("better"), str) and SAFE_TOKEN.fullmatch(metric["better"]) else None,
        "differences": [item for item in (project_difference(diff) for diff in metric.get("differences") or []) if item],
        "exploratory": bool(metric.get("exploratory")),
        "kind": metric.get("kind") if isinstance(metric.get("kind"), str) and SAFE_KEY.fullmatch(metric["kind"]) else None,
        "measured": bool(metric.get("measured")),
        "metric": name,
        "unit": metric.get("unit") if isinstance(metric.get("unit"), str) and SAFE_LABEL.fullmatch(metric["unit"]) else None,
    }


def project_experiment(definition, readout, dropped, patterns, redactions):
    if not isinstance(definition, dict) or not isinstance(readout, dict):
        return None
    if definition.get("status") != "concluded" or readout.get("experiment", {}).get("status") not in (None, "concluded"):
        dropped["experiments_omitted"] += 1
        return None
    ident = definition.get("id")
    if not isinstance(ident, str) or not SAFE_ID.fullmatch(ident):
        return None
    info = readout.get("experiment") if isinstance(readout.get("experiment"), dict) else {}
    name = sanitize(definition.get("name") or "", patterns, redactions)
    hypothesis = sanitize(definition.get("hypothesis") or "", patterns, redactions)
    arms = []
    for arm in readout.get("arms") or []:
        if not isinstance(arm, dict):
            continue
        arm_name = arm.get("name")
        if not isinstance(arm_name, str) or not SAFE_TOKEN.fullmatch(arm_name):
            continue
        mix = []
        for crew_row in arm.get("crew_mix") or []:
            if not isinstance(crew_row, dict):
                continue
            crew, tasks = crew_row.get("crew"), crew_row.get("tasks")
            if is_gap_crew(crew) or is_gap_model(crew_row.get("model")):
                dropped["experiments"] += 1
                continue
            if isinstance(crew, str) and SAFE_TOKEN.fullmatch(crew) and is_number(tasks):
                mix.append({"crew": crew, "tasks": tasks})
        segments = []
        for segment in arm.get("segments") or []:
            if isinstance(segment, dict) and is_number(segment.get("segment")) and is_number(segment.get("n")):
                segments.append({"n": segment["n"], "segment": segment["segment"]})
        projected = {
            "control": bool(arm.get("control")),
            "crew_mix": mix,
            "drifted": bool(arm.get("drifted")),
            "n": whole(arm.get("n")) or 0,
            "name": arm_name,
            "segments": segments,
            "tasks_explorer_unobserved": whole(arm.get("tasks_explorer_unobserved")) or 0,
            "tasks_with_explorer_call": whole(arm.get("tasks_with_explorer_call")) or 0,
            "weight": arm.get("weight") if is_number(arm.get("weight")) else None,
        }
        if arm.get("retired_segment") is None or is_number(arm.get("retired_segment")):
            projected["retired_segment"] = arm.get("retired_segment")
        usage = project_usage(arm.get("effort_breakdown"), dropped, "experiments")
        if usage is not None:
            projected["usage"] = usage
        arms.append(projected)
    warnings = collections.Counter()
    for warning in readout.get("warnings") or []:
        if isinstance(warning, dict) and isinstance(warning.get("kind"), str) and SAFE_KEY.fullmatch(warning["kind"]):
            warnings[warning["kind"]] += 1
    verdict = readout.get("verdict") if isinstance(readout.get("verdict"), dict) else {}
    reasons = [
        sanitize(reason, patterns, redactions)
        for reason in verdict.get("reasons") or []
        if isinstance(reason, str)
    ]
    enrollment = numeric_map(readout.get("enrollment")) or {}
    lagging = readout.get("lagging") if isinstance(readout.get("lagging"), dict) else {}
    ratio = readout.get("sample_ratio") if isinstance(readout.get("sample_ratio"), dict) else {}
    per_protocol = readout.get("per_protocol") if isinstance(readout.get("per_protocol"), dict) else None
    guardrails = []
    for guard in readout.get("guardrails") or []:
        if not isinstance(guard, dict):
            continue
        metric = guard.get("metric")
        if not isinstance(metric, str) or not SAFE_TOKEN.fullmatch(metric):
            continue
        arms_out = []
        for arm in guard.get("arms") or []:
            if not isinstance(arm, dict) or not isinstance(arm.get("arm"), str) or not SAFE_TOKEN.fullmatch(arm["arm"]):
                continue
            item = {
                "arm": arm["arm"],
                "estimate": arm.get("estimate") if arm.get("estimate") is None or is_number(arm.get("estimate")) else None,
                "status": arm.get("status") if isinstance(arm.get("status"), str) and SAFE_KEY.fullmatch(arm["status"]) else None,
            }
            interval = number_list(arm.get("interval"), 2)
            if interval is not None:
                item["interval"] = interval
            if is_number(arm.get("limit")) or isinstance(arm.get("limit"), str) and SAFE_LABEL.fullmatch(arm["limit"]):
                item["limit"] = arm["limit"]
            arms_out.append(item)
        threshold = guard.get("threshold")
        guardrails.append({
            "arms": arms_out,
            "metric": metric,
            "threshold": threshold if isinstance(threshold, str) and SAFE_LABEL.fullmatch(threshold) else None,
        })
    concluded = definition.get("concluded_arm")
    return {
        "arms": arms,
        "as_of": readout.get("as_of") if isinstance(readout.get("as_of"), str) else None,
        "concluded_arm": concluded if concluded is None or (isinstance(concluded, str) and SAFE_TOKEN.fullmatch(concluded)) else None,
        "enrollment": enrollment,
        "guardrail_definition": {
            key: value for key, value in (definition.get("guardrails") or {}).items()
            if isinstance(key, str) and SAFE_KEY.fullmatch(key) and isinstance(value, str) and SAFE_LABEL.fullmatch(value)
        } if isinstance(definition.get("guardrails"), dict) else {},
        "guardrails": guardrails,
        "horizon_at": info.get("horizon_at") if isinstance(info.get("horizon_at"), str) else None,
        "hypothesis": hypothesis,
        "id": ident,
        "lagging": {
            "open_regression_windows": whole(lagging.get("open_regression_windows")) or 0,
            "open_tasks": whole(lagging.get("open_tasks")) or 0,
            "regression_window_days": whole(lagging.get("regression_window_days")) or 0,
        },
        "max_days": whole(definition.get("max_days")),
        "metrics": [item for item in (project_metric(metric) for metric in readout.get("metrics") or []) if item],
        "min_delivered_rate": info.get("min_delivered_rate") if is_number(info.get("min_delivered_rate")) else None,
        "min_sample": whole(definition.get("min_sample")),
        "mode": definition.get("mode") if isinstance(definition.get("mode"), str) and SAFE_KEY.fullmatch(definition["mode"]) else None,
        "name": name,
        "per_protocol": None if per_protocol is None else {
            "label": sanitize(per_protocol.get("label") or "", patterns, redactions)
            if isinstance(per_protocol.get("label"), str) else None,
            "metric": project_metric(per_protocol.get("metric")),
        },
        "population": {
            "complexity": [
                item for item in (definition.get("population") or {}).get("complexity") or []
                if isinstance(item, str) and SAFE_KEY.fullmatch(item)
            ],
        } if isinstance(definition.get("population"), dict) else {},
        "primary_metric": definition.get("primary_metric")
        if isinstance(definition.get("primary_metric"), str) and SAFE_TOKEN.fullmatch(definition["primary_metric"]) else None,
        "sample_ratio": {
            "alpha": ratio.get("alpha") if is_number(ratio.get("alpha")) else None,
            "chi_square": ratio.get("chi_square") if is_number(ratio.get("chi_square")) else None,
            "df": whole(ratio.get("df")),
            "mismatch": bool(ratio.get("mismatch")),
            "p_value": ratio.get("p_value") if is_number(ratio.get("p_value")) else None,
        },
        "schema_version": SCHEMA_VERSION,
        "segment": whole(definition.get("segment")),
        "started_at": info.get("started_at") if isinstance(info.get("started_at"), str) else None,
        "status": "concluded",
        "updated_at": definition.get("updated_at") if isinstance(definition.get("updated_at"), str) else None,
        "verdict": {
            "arm": verdict.get("arm") if verdict.get("arm") is None
            or (isinstance(verdict.get("arm"), str) and SAFE_TOKEN.fullmatch(verdict["arm"])) else None,
            "horizon_reached": bool(verdict.get("horizon_reached")),
            "label": sanitize(verdict.get("label") or "", patterns, redactions)
            if isinstance(verdict.get("label"), str) else None,
            "reasons": reasons,
            "state": verdict.get("state") if isinstance(verdict.get("state"), str) and SAFE_KEY.fullmatch(verdict["state"]) else None,
        },
        "warning_kinds": dict(sorted(warnings.items())),
    }


def empty_dropped():
    return {
        "experiments": 0,
        "experiments_omitted": 0,
        "implementers": 0,
        "implementers_by_tier": 0,
        "metrics_diff": 0,
        "metrics_durations": 0,
        "metrics_friction": 0,
        "metrics_tokens": 0,
        "pilots": 0,
        "reliability": 0,
        "reviewers_provisional": 0,
        "reviewers_settled": 0,
    }


def assemble_scorecards(cards, until_supported, dropped):
    reviewers = {
        "provisional": project_board(cards["reviewers"], True, dropped, "reviewers_provisional", settled=False),
        "settled": project_board(cards["reviewers_settled"], False, dropped, "reviewers_settled", settled=True)
        if until_supported else None,
    }
    return {
        "implementers": project_board(cards["implementers"], False, dropped, "implementers"),
        "implementers_by_tier": project_cells(cards["implementers_by_type"], dropped),
        "min_support_default": MIN_SUPPORT_DEFAULT,
        "pilots": project_board(cards["pilots"], False, dropped, "pilots"),
        "reviewers": reviewers,
        "roles": list(ROLES),
        "roles_omitted": ["orchestrators"],
        "schema_version": SCHEMA_VERSION,
    }


def assemble_meta(docs_without_meta, generated_at, version, workspace, until_supported, dropped, redactions):
    def span(board):
        if not isinstance(board, dict):
            return None
        window = board.get("window") or {}
        return {"since": window.get("since"), "until": window.get("until"), "key": window.get("key") or window.get("label")}

    scorecards = docs_without_meta["scorecards"]
    windows = {
        "experiments": [item.get("as_of") for item in docs_without_meta["experiments"]["experiments"]],
        "implementers": span(scorecards["implementers"]),
        "implementers_by_tier": span(scorecards["implementers_by_tier"]),
        "metrics": docs_without_meta["metrics"]["durations"]["window"],
        "pilots": span(scorecards["pilots"]),
        "reliability": docs_without_meta["reliability"]["window"],
        "reviewers_provisional": span(scorecards["reviewers"]["provisional"]),
    }
    recorded = dict(dropped)
    if until_supported:
        windows["reviewers_settled"] = span(scorecards["reviewers"]["settled"])
    else:
        recorded.pop("reviewers_settled", None)
    return {
        "dropped": recorded,
        "free_text_redactions": redactions,
        "generated_at": generated_at,
        "orbit_version": version,
        "reviewer_settled": until_supported,
        "schema_version": SCHEMA_VERSION,
        "windows": windows,
        "workspace": workspace,
    }


def collect(workspace, dashboard, generated_at, version):
    print("scorecards", file=sys.stderr)
    until_supported = scorecard_supports_until()
    ident = workspace_id(workspace)
    cards = {
        "implementers": orbit_json(
            ["agents", "scorecard", "--role", "implementers", "--window", WINDOW], workspace
        ),
        "implementers_by_type": orbit_json(
            ["agents", "scorecard", "--role", "implementers", "--window", WINDOW, "--by-type"], workspace
        ),
        "reviewers": orbit_json(
            ["agents", "scorecard", "--role", "reviewers", "--window", WINDOW], workspace
        ),
        "pilots": orbit_json(
            ["agents", "scorecard", "--role", "pilots", "--window", WINDOW], workspace
        ),
    }
    if until_supported:
        cards["reviewers_settled"] = orbit_json(
            ["agents", "scorecard", "--role", "reviewers", "--window", WINDOW, "--until", SETTLED_UNTIL],
            workspace,
        )
    print("metrics", file=sys.stderr)
    scope = {"workspace": ident}
    durations = http_json(dashboard, "/api/diagnostics/implement_one", {"since": WINDOW, "outcome": "succeeded", **scope})
    completions = http_json(dashboard, "/api/diagnostics/completions", {"since": WINDOW, **scope})
    defects = http_json(dashboard, "/api/diagnostics/defects", {"since": WINDOW, **scope})
    tokens = http_json(
        dashboard, "/api/diagnostics/task_tokens",
        {"since": WINDOW, "outcome": "done", "scope": "all", **scope},
    )
    turns = http_json(
        dashboard, "/api/diagnostics/turns_to_edit",
        {"since": WINDOW, "outcome": "done", **scope},
    )
    diff = http_json(dashboard, "/api/diagnostics/diff_stats", {"since": WINDOW, **scope})
    friction = http_json(
        dashboard, "/api/diagnostics/delivery_friction",
        {"since": WINDOW, "families": ",".join(FRICTION_FAMILIES), **scope},
    )
    outcome_mix = http_json(dashboard, "/api/tasks/completion-by-complexity", scope)
    print("reliability", file=sys.stderr)
    reliability = http_json(dashboard, "/api/metrics/reliability", {"window": WINDOW})
    print("experiments", file=sys.stderr)
    listed = orbit_json(["experiment", "list"], workspace)
    experiments = listed.get("experiments") if isinstance(listed, dict) else None
    if not isinstance(experiments, list):
        raise SystemExit("orbit experiment list did not return experiments")
    readouts = []
    for experiment in experiments:
        if not isinstance(experiment, dict):
            continue
        if experiment.get("status") != "concluded":
            readouts.append((experiment, None))
            continue
        ident_exp = experiment.get("id")
        if not isinstance(ident_exp, str):
            continue
        readouts.append((experiment, orbit_json(["experiment", "readout", ident_exp], workspace)))
    return project_all(
        cards=cards,
        until_supported=until_supported,
        durations=durations,
        completions=completions,
        defects=defects,
        tokens=tokens,
        turns=turns,
        diff=diff,
        friction=friction,
        outcome_mix=outcome_mix,
        reliability=reliability,
        experiments=readouts,
        generated_at=generated_at,
        version=version,
        workspace=workspace,
    )


def project_all(cards, until_supported, durations, completions, defects, tokens, turns, diff,
                friction, outcome_mix, reliability, experiments, generated_at, version, workspace):
    dropped = empty_dropped()
    patterns = forbidden_patterns(host_names())
    redactions = [0]
    scorecards = assemble_scorecards(cards, until_supported, dropped)
    metrics = {
        "completion_by_complexity": project_outcome_mix(outcome_mix),
        "completions": project_completions(completions),
        "defects": project_defects(defects),
        "diff": project_diff(diff, dropped),
        "durations": project_durations(durations, dropped),
        "friction": project_friction(friction, dropped),
        "outcome": "succeeded",
        "schema_version": SCHEMA_VERSION,
        "tokens": project_tokens(tokens, dropped),
        "turns": project_turns(turns),
        "window": WINDOW,
        "workspace": workspace,
    }
    reliability_doc = project_reliability(reliability, dropped)
    reliability_doc["schema_version"] = SCHEMA_VERSION
    projected_experiments = []
    for definition, readout in experiments:
        if readout is None:
            if isinstance(definition, dict) and definition.get("status") != "concluded":
                dropped["experiments_omitted"] += 1
            continue
        projected = project_experiment(definition, readout, dropped, patterns, redactions)
        if projected is not None:
            projected_experiments.append(projected)
    projected_experiments.sort(key=lambda item: (item.get("name") or "", item["id"]))
    experiments_doc = {
        "experiments": projected_experiments,
        "schema_version": SCHEMA_VERSION,
        "source": "orbit experiment list --json; orbit experiment readout --json <id>",
    }
    docs = {
        "experiments": experiments_doc,
        "metrics": metrics,
        "reliability": reliability_doc,
        "scorecards": scorecards,
    }
    docs["meta"] = assemble_meta(docs, generated_at, version, workspace, until_supported, dropped, redactions[0])
    return docs


def guard(docs, hosts=None):
    patterns = forbidden_patterns(hosts if hosts is not None else host_names())
    scan(docs, patterns)
    assert_no_gap_values(docs)
    roles = docs["scorecards"]["roles"]
    if roles != list(ROLES) or "orchestrators" in roles:
        raise SystemExit("scorecards roles must be implementers, reviewers and pilots")
    provisional = docs["scorecards"]["reviewers"]["provisional"]
    if provisional.get("provisional") is not True:
        raise SystemExit("the trailing reviewer board must be labelled provisional")
    settled = docs["scorecards"]["reviewers"]["settled"]
    if docs["meta"]["reviewer_settled"]:
        if not isinstance(settled, dict) or settled.get("provisional") is not False or settled.get("settled") is not True:
            raise SystemExit("a settled reviewer board is required when --until is supported")
    elif settled is not None:
        raise SystemExit("settled reviewer board must be absent when --until is unsupported")
    for experiment in docs["experiments"]["experiments"]:
        if experiment.get("status") != "concluded":
            raise SystemExit("experiments file contains an experiment that is not concluded")


def write_snapshot(out, docs):
    out.mkdir(parents=True, exist_ok=True)
    raw = out / "raw"
    raw.mkdir(exist_ok=True)
    text = {key: dump(docs[key]) for key in PUBLIC_KEYS}
    bundle_text = dump(docs)
    reloaded = json.loads(bundle_text)
    for key, body in text.items():
        if dump(reloaded[key]) != body:
            raise SystemExit(f"serialization is not stable for {key}")
    if dump(reloaded) != bundle_text:
        raise SystemExit("bundle serialization is not stable")
    for key, body in text.items():
        (out / f"{key}.json").write_text(body)
    (raw / "bundle.json").write_text(bundle_text)


def load_bundle(source):
    path = pathlib.Path(source)
    if path.is_dir():
        for candidate in (path / "bundle.json", path / "raw" / "bundle.json"):
            if candidate.is_file():
                path = candidate
                break
        else:
            raise SystemExit(f"no bundle.json under {source}")
    try:
        docs = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} is not JSON") from exc
    if not isinstance(docs, dict) or set(docs) != set(PUBLIC_KEYS):
        raise SystemExit("bundle must contain scorecards, metrics, reliability, experiments and meta")
    return docs


def replay(source, out):
    docs = load_bundle(source)
    guard(docs)
    write_snapshot(pathlib.Path(out), docs)


def generated_now():
    proc = subprocess.run(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def self_test():
    hosts = ["dk-server-1", "dk-server-2"]
    dropped = empty_dropped()
    card = {
        "role": "implementers",
        "since": "2026-10-09T00:00:00Z",
        "until": "2026-11-08T00:00:00Z",
        "window": "30d",
        "min_support": 10,
        "unit": "tasks",
        "fleet_average": 100,
        "tasks_scanned": 3,
        "provisional": None,
        "terms": [
            {"key": "weighted_landed", "label": "Landed", "weight": 1, "group": "credit", "definition": "ORB-1 /home/secret"},
        ],
        "rows": [
            {
                "crew": "opus", "model": "claude-opus", "units": 12, "rank": 1, "score": 110.0, "raw": 112.0,
                "below_support": False, "unjudged": False,
                "counts": {"weighted_landed": 10, "task_id": "ORB-9"},
                "per_100": {"weighted_landed": 83.3},
                "effort_breakdown": [{
                    "crew": "opus", "model": "claude-opus", "invocations": 4, "duration_ms": 5,
                    "input_tokens": 6, "output_tokens": 7, "provider_cost_usd": 1.5,
                    "provider_cost_count": 4, "reasoning_effort": "high",
                    "host": "dk-server-2", "path": "/home/daniel/workspace",
                }],
                "slowest_task": "ORB-99",
                "run_id": "jrun-20261108-0000-aa",
            },
            {"crew": "crew unknown", "model": "claude-opus", "units": 20, "rank": 2, "score": 90, "below_support": False},
            {"crew": "haiku", "model": "model unknown", "units": 15, "rank": 3, "score": 80, "below_support": False},
            {"crew": "crew unavailable", "model": "gpt", "units": 11, "rank": 4, "score": 70, "below_support": False},
            {"crew": "small", "model": "gpt-small", "units": 4, "rank": 9, "score": 130, "below_support": True},
        ],
    }
    board = project_board(card, False, dropped, "implementers")
    assert dropped["implementers"] == 3, dropped
    assert [row["crew"] for row in board["rows"]] == ["opus", "small"]
    assert board["rows"][0]["rank"] == 1
    assert board["rows"][1]["rank"] is None and board["rows"][1]["below_support"] is True
    assert "task_id" not in board["rows"][0]["counts"]
    assert "ORB-99" not in json.dumps(board)
    assert "dk-server-2" not in json.dumps(board)
    assert "/home/" not in json.dumps(board)
    assert board["rows"][0]["unit"] == "tasks"
    assert board["rows"][0]["usage"]["provider_cost_usd"] == 1.5
    assert "definition" not in json.dumps(board["terms"])

    cells = project_cells({
        "min_support": 10,
        "since": card["since"],
        "until": card["until"],
        "window": "30d",
        "cells": [
            {"tier": "low", "type": "feature", "crew": "opus", "model": "claude-opus", "n": 12, "crew_mean": 101, "score": 101},
            {"tier": "low", "type": "feature", "crew": "crew unknown", "model": "claude-opus", "n": 12, "crew_mean": 90},
            {"tier": "low", "type": "feature", "crew": "tiny", "model": "gpt", "n": 3, "crew_mean": 140},
            {"tier": "low", "type": "feature", "crew": "zero", "model": "gpt", "n": 0, "crew_mean": 100},
        ],
    }, dropped)
    assert dropped["implementers_by_tier"] == 1
    assert [cell["crew"] for cell in cells["cells"]] == ["opus", "tiny"]
    assert cells["cells"][0]["rank"] == 1
    assert cells["cells"][1]["rank"] is None

    patterns = forbidden_patterns(hosts)
    redactions = [0]
    experiment = project_experiment(
        {
            "id": "exp-alpha",
            "name": "arm weight",
            "status": "concluded",
            "mode": "live",
            "hypothesis": "Does this beat ORB-42 on dk-server-2 via /home/daniel/note in ws_secret?",
            "primary_metric": "delivery_done",
            "concluded_arm": "treatment",
            "min_sample": 10,
            "max_days": 14,
            "segment": 1,
            "salt": "secret-salt",
            "created_by": "dk-server-2",
            "population": {"complexity": ["low", "medium"], "tags_exclude": ["ORB-1"]},
            "guardrails": {"delivery_done_rate": ">= 0.9"},
            "updated_at": "2026-11-01T00:00:00Z",
        },
        {
            "as_of": "2026-11-08T00:00:00Z",
            "experiment": {"status": "concluded", "started_at": "2026-10-01T00:00:00Z", "horizon_at": "2026-11-01T00:00:00Z", "min_delivered_rate": 0.5},
            "enrollment": {"analysed": 20, "unreadable": 0},
            "arms": [{
                "name": "treatment", "control": False, "weight": 1, "n": 10, "drifted": False,
                "segments": [{"segment": 1, "n": 10}],
                "crew_mix": [{"crew": "opus", "tasks": 8}, {"crew": "crew unknown", "tasks": 2}],
                "assignment_digests": ["jrun-abc"],
                "run_digests": ["/home/daniel/run"],
                "effort_breakdown": [{
                    "crew": "opus", "model": "claude-opus", "invocations": 1, "duration_ms": 1,
                    "input_tokens": 1, "output_tokens": 1, "provider_cost_usd": 0.25, "provider_cost_count": 1,
                    "reasoning_effort": "medium",
                }],
            }],
            "metrics": [{
                "metric": "delivery_done", "kind": "rate", "better": "higher", "unit": "share",
                "exploratory": False, "measured": True,
                "arms": [{"arm": "treatment", "n": 10, "mean": 0.5, "mean_interval": [0.2, 0.8]}],
                "differences": [{
                    "arm": "treatment",
                    "overall": {"estimate": 0.1, "interval": [-0.1, 0.3], "cells_dropped": ["hard"]},
                    "by_complexity": [{"complexity": "low", "n_arm": 4, "n_control": 4, "estimate": 0.1, "interval": [0.0, 0.2]}],
                }],
            }],
            "per_protocol": {"label": "delivered runs", "metric": {"metric": "delivery_done", "kind": "rate", "better": "higher", "unit": "share", "exploratory": False, "measured": True, "arms": [], "differences": []}},
            "guardrails": [{"metric": "delivery_done_rate", "threshold": ">= 0.9", "arms": [{"arm": "treatment", "estimate": 0.95, "interval": [0.8, 1.0], "status": "ok"}]}],
            "sample_ratio": {"chi_square": 0.1, "df": 1, "p_value": 0.7, "alpha": 0.05, "mismatch": False, "segments": [{"secret": "jrun-1"}]},
            "lagging": {"open_tasks": 1, "open_regression_windows": 0, "regression_window_days": 30},
            "verdict": {"state": "inconclusive", "arm": None, "label": "inconclusive", "horizon_reached": True, "reasons": ["still open"]},
            "warnings": [{"kind": "lagging", "message": "task ORB-7 on dk-server-2 /home/daniel"}],
        },
        dropped,
        patterns,
        redactions,
    )
    assert experiment["status"] == "concluded"
    assert "ORB-" not in json.dumps(experiment)
    assert "jrun-" not in json.dumps(experiment)
    assert "dk-server" not in json.dumps(experiment)
    assert "/home/" not in json.dumps(experiment)
    assert "ws_secret" not in json.dumps(experiment)
    assert "secret-salt" not in json.dumps(experiment)
    assert experiment["arms"][0]["crew_mix"] == [{"crew": "opus", "tasks": 8}]
    assert dropped["experiments"] == 1
    assert experiment["metrics"][0]["arms"][0]["mean_interval"] == [0.2, 0.8]
    assert experiment["verdict"]["state"] == "inconclusive"
    assert redactions[0] >= 1

    omitted = empty_dropped()
    assert project_experiment({"id": "exp-run", "status": "running"}, {"experiment": {"status": "running"}}, omitted, patterns, [0]) is None

    reliability = project_reliability({
        "scope": "fleet",
        "window": {"label": "30d", "since": "2026-10-09T00:00:00Z", "until": "2026-11-08T00:00:00Z", "bucket": "day"},
        "unreadable_workspaces": ["/home/daniel/ws"],
        "totals": {
            "job_runs": {
                "counts": {key: (2 if key == "failed" else 8 if key == "succeeded" else 1 if key == "total" else 0) for key in OUTCOME_COUNTS},
                "failure_rate": {
                    "numerator": 2, "denominator": 10, "denominator_label": FAILURE_RATE_LABEL,
                    "value": 0.2, "low_sample": True,
                },
                "truncated": False,
            },
            "recovery": {
                "per_step_invocation": {"numerator": 1, "denominator": 10, "denominator_label": "step-activity invocations", "value": 0.1, "low_sample": True},
                "per_job_run": {"numerator": 1, "denominator": 4, "denominator_label": "job runs with any recorded invocation", "value": 0.25, "low_sample": True},
            },
        },
        "workspaces": [{
            "workspace_id": "ws_secret",
            "workspace_name": "dk-server-2",
            "job_runs": {
                "counts": {"failed": 2, "succeeded": 8, "total": 10},
                "by_job": [
                    {"job_id": "task-delivery", "counts": {"failed": 2, "succeeded": 8, "total": 10}},
                    {"job_id": "/home/daniel/job", "counts": {"failed": 1, "succeeded": 0, "total": 1}},
                ],
                "over_time": [{
                    "bucket_start": "2026-11-07T00:00:00Z",
                    "bucket_end": "2026-11-08T00:00:00Z",
                    "counts": {"failed": 2, "succeeded": 8, "total": 10},
                }],
                "observed_states": {"success": 8, "failed": 2},
            },
            "recovery": {"by_activity": [
                {"activity_id": "implement_one", "role": "step", "invocation_count": 10, "job_run_count": 4},
                {"activity_id": "/tmp/secret-activity", "role": "step", "invocation_count": 1, "job_run_count": 1},
            ]},
        }],
    }, dropped)
    blob = json.dumps(reliability)
    assert "dk-server" not in blob and "/home/" not in blob and "jrun-" not in blob and "ws_secret" not in blob
    assert reliability["by_job"][0]["job_id"] == "task-delivery"
    assert reliability["unreadable_workspace_count"] == 1
    assert dropped["reliability"] >= 1

    durations = project_durations({
        "outcome": "succeeded",
        "window": {"key": "30d", "since": "2026-10-09T00:00:00Z", "until": "2026-11-08T00:00:00Z", "bucket_seconds": 86400, "lead_buckets": 0},
        "truncated": False,
        "buckets": [],
        "current": {"all": {"n": 1, "avg": 10, "p50": 10, "p95": 10}},
        "previous": None,
        "actors": [
            {"actor": "opus / claude-opus", "n": 4, "avg": 10, "p50": 9, "p95": 12},
            {"actor": "crew unknown / claude-opus", "n": 2, "avg": 10, "p50": 10, "p95": 10},
            {"actor": "haiku / model unknown", "n": 2, "avg": 10, "p50": 10, "p95": 10},
        ],
        "slowest": [{"task_id": "ORB-1", "actor": "opus / claude-opus", "duration_ms": 9}],
        "implement_one_by_complexity": [],
    }, dropped)
    assert "ORB-1" not in json.dumps(durations)
    assert [row["actor"] for row in durations["actors"]] == ["opus / claude-opus"]
    assert dropped["metrics_durations"] == 2

    docs = {
        "scorecards": {
            "schema_version": 1,
            "roles": list(ROLES),
            "roles_omitted": ["orchestrators"],
            "min_support_default": 10,
            "implementers": board,
            "implementers_by_tier": cells,
            "reviewers": {"provisional": {**board, "role": "reviewers", "provisional": True, "settled": False}, "settled": None},
            "pilots": {**board, "role": "pilots"},
        },
        "metrics": {
            "schema_version": 1,
            "window": "30d",
            "outcome": "succeeded",
            "workspace": "orbit",
            "durations": durations,
            "completions": project_completions({"window": durations["window"], "buckets": [], "current": {"done": {"total": 1, "low": 1, "medium": 0, "hard": 0, "other": 0}, "rejected": 0, "archived": 0}, "lead_buckets": [], "previous": None, "undated": {"done": {"total": 0, "low": 0, "medium": 0, "hard": 0, "other": 0}, "rejected": 0, "archived": 0}}),
            "defects": project_defects({"window": durations["window"], "buckets": [], "current": {"total": 0, "lineage": {}, "origin": {}}, "lead_buckets": [], "previous": None}),
            "tokens": {"source": "fixture", "series": []},
            "turns": {"source": "fixture", "series": []},
            "diff": {"source": "fixture", "crews": []},
            "friction": {"source": "fixture", "families": []},
            "completion_by_complexity": {"scope": "all_time", "by_complexity": [], "source": "fixture"},
        },
        "reliability": reliability,
        "experiments": {
            "schema_version": 1,
            "source": "orbit experiment list --json; orbit experiment readout --json <id>",
            "experiments": [experiment],
        },
    }
    docs["meta"] = assemble_meta(docs, "2026-11-08T00:00:00Z", "0.47.0", "orbit", False, dropped, redactions[0])
    assert "reviewers_settled" not in docs["meta"]["dropped"]
    assert docs["meta"]["reviewer_settled"] is False
    assert docs["scorecards"]["reviewers"]["provisional"]["provisional"] is True
    guard(docs, hosts)
    out = pathlib.Path(".orbit/tmp/analytics-self-test")
    replay_out = pathlib.Path(".orbit/tmp/analytics-self-test-replay")
    write_snapshot(out, docs)
    replay(out / "raw", replay_out)
    for name in PUBLIC_KEYS:
        left = (out / f"{name}.json").read_bytes()
        right = (replay_out / f"{name}.json").read_bytes()
        if left != right:
            raise SystemExit(f"self-test replay diverged for {name}")
    blob = (out / "raw" / "bundle.json").read_text()
    for needle in ("ORB-", "jrun-", "dk-server-1", "dk-server-2", "/home/", "ws_", "model unknown", "crew unknown", "crew unavailable"):
        if needle in blob:
            raise SystemExit(f"self-test output still contains {needle}")
    print("self-test ok")


def main():
    parser = argparse.ArgumentParser(description="Write the public Orbit analytics snapshot")
    parser.add_argument("--out", help="directory for the public JSON and raw/bundle.json")
    parser.add_argument("--from", dest="source", help="raw directory or bundle.json to replay")
    parser.add_argument("--workspace", default="orbit", help="Orbit workspace name (default orbit)")
    parser.add_argument(
        "--dashboard-url",
        default=os.environ.get("ORBIT_DASHBOARD_URL", "http://127.0.0.1:7878"),
        help="loopback dashboard origin (default http://127.0.0.1:7878 or ORBIT_DASHBOARD_URL)",
    )
    parser.add_argument("--self-test", action="store_true", help="run the offline projection checks")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.out:
        parser.error("--out is required")
    if args.source:
        replay(args.source, args.out)
        return
    dashboard = check_dashboard(args.dashboard_url)
    docs = collect(args.workspace, dashboard, generated_now(), orbit_version())
    guard(docs)
    write_snapshot(pathlib.Path(args.out), docs)


if __name__ == "__main__":
    main()
