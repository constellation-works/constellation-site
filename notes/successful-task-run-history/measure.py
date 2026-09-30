#!/usr/bin/env python3
"""Print aggregate delivery-run measurements; never print task or run identities.

Uses only the Python standard library. Supply the operator's own store paths and
workspace binding. SQLite connections are read-only; task event files are read
without changing them. See method.md for cohort and snapshot limitations.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import statistics


RECOVERY = {"step_failure_recovery", "pr_conflict_recovery"}
TERMINAL = {"success", "failed", "timeout", "interrupted", "cancelled", "skipped"}
COMPLEXITIES = {"low", "medium", "hard", "xhard"}


def instant(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return result.astimezone(timezone.utc)


def stamp(value):
    return value.isoformat().replace("+00:00", "Z")


def fingerprint(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def complexity(path):
    # Read the scalar metadata field, not descriptions, plans, comments or logs.
    for line in path.read_text().splitlines():
        if line.startswith("complexity:"):
            value = line.partition(":")[2].strip().strip("\"'")
            return value if value in COMPLEXITIES else "unknown"
    return "unknown"


def summary(items):
    final = sum(t["final_ms"] for t in items)
    extra = sum(t["extra_ms"] for t in items)
    return {
        "tasks": len(items),
        "delivery_runs": sum(t["runs"] for t in items),
        "final_successful_run_ms": final,
        "earlier_run_ms": extra,
        "all_delivery_run_ms": final + extra,
        "earlier_over_final_ratio": extra / final if final else None,
        "median_all_delivery_run_ms": statistics.median(t["total_ms"] for t in items) if items else None,
        "median_final_successful_run_ms": statistics.median(t["final_ms"] for t in items) if items else None,
        "median_paired_earlier_over_final_ratio": statistics.median(t["extra_ms"] / t["final_ms"] for t in items) if items else None,
    }


def measure(args):
    since, until, cutoff = map(instant, (args.since, args.until, args.cutoff))
    if not since < until <= cutoff:
        raise ValueError("require since < until <= cutoff")
    started = datetime.now(timezone.utc)
    conn = sqlite3.connect(Path(args.run_db).resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("ATTACH DATABASE ? AS task_index", (Path(args.task_index).resolve().as_uri() + "?mode=ro",))
    conn.execute("BEGIN")
    # Establish both database snapshots before reading nontransactional bundles.
    run_rows = conn.execute("SELECT COUNT(*) FROM job_runs").fetchone()[0]
    bindings = conn.execute(
        "SELECT task_id,canonical_path FROM task_index.task_bundle_bindings WHERE workspace_id=?",
        (args.workspace,),
    ).fetchall()
    cohort, files, done_types = {}, {}, Counter()
    for binding in bindings:
        root = Path(binding["canonical_path"])
        events_path = root / "events.jsonl"
        before = fingerprint(events_path)
        first_done = None
        with events_path.open() as stream:
            for line in stream:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("to_status") != "done":
                    continue
                at = instant(event["at"])
                if at < cutoff and (first_done is None or at < first_done[0]):
                    first_done = at, event.get("type", "unknown")
        if fingerprint(events_path) != before:
            raise RuntimeError("task events changed during analysis; rerun")
        files[events_path] = before
        if first_done and since <= first_done[0] < until:
            meta_path = root / "task.yaml"
            files[meta_path] = fingerprint(meta_path)
            event_type = first_done[1]
            if event_type not in {"status_changed", "forced", "review_approved", "landing_completed"}:
                event_type = "other"
            done_types[event_type] += 1
            cohort[binding["task_id"]] = {
                "done": first_done[0], "complexity": complexity(meta_path),
                "runs": [], "unusable_runs": 0, "multi_task": False,
            }

    query = """
        SELECT run_id,state,started_at,finished_at,duration_ms,
               retry_source_run_id,crew_model,json_extract(input_json,'$.task_ids') AS task_ids
        FROM job_runs
        WHERE workspace_id=? AND job_id='task_pr_pipeline'
          AND started_at IS NOT NULL AND julianday(started_at)<julianday(?) AND json_valid(input_json)
    """
    for record in conn.execute(query, (args.workspace, stamp(until))):
        run = dict(record)
        task_ids = json.loads(run.pop("task_ids") or "[]")
        if not isinstance(task_ids, list):
            continue
        task_ids = set(task_ids)
        for task_id in task_ids & cohort.keys():
            task = cohort[task_id]
            if instant(run["started_at"]) > task["done"]:
                continue
            if len(task_ids) != 1:
                task["multi_task"] = True
            if (run["state"] not in TERMINAL or not run["finished_at"]
                    or instant(run["finished_at"]) >= cutoff or run["duration_ms"] is None
                    or run["duration_ms"] < 0):
                task["unusable_runs"] += 1
                continue
            task["runs"].append(run)

    exclusions, groups, states, models = Counter(), defaultdict(list), Counter(), Counter()
    selected_runs, final_run_ids, extra_run_ids, retry_sources = {}, set(), set(), set()
    diagnostics = Counter()
    for task_id, task in cohort.items():
        successful = [r for r in task["runs"] if r["state"] == "success"]
        if not successful:
            exclusions["no_successful_pr_pipeline_run_by_cutoff"] += 1
            continue
        if task["multi_task"]:
            exclusions["shared_delivery_run"] += 1
            continue
        if task["unusable_runs"]:
            exclusions["incomplete_or_unusable_delivery_run"] += 1
            continue
        final = max(successful, key=lambda r: (instant(r["started_at"]), r["run_id"]))
        final_run_ids.add(final["run_id"])
        total = sum(r["duration_ms"] for r in task["runs"])
        item = {
            "runs": len(task["runs"]), "total_ms": total,
            "final_ms": final["duration_ms"], "extra_ms": total - final["duration_ms"],
        }
        groups["all"].append(item)
        groups["multiple_runs" if item["runs"] > 1 else "one_run"].append(item)
        groups[task["complexity"]].append(item)
        models[final["crew_model"] or "unrecorded"] += 1
        diagnostics["final_run_finished_after_task_done"] += instant(final["finished_at"]) > task["done"]
        diagnostics["runs_started_before_cohort_week"] += sum(instant(r["started_at"]) < since for r in task["runs"])
        for run in task["runs"]:
            if run["run_id"] in selected_runs:
                raise RuntimeError("delivery run counted for more than one task")
            selected_runs[run["run_id"]] = {"task_id": task_id}
            states[run["state"]] += 1
            if run["run_id"] != final["run_id"]:
                extra_run_ids.add(run["run_id"])
            if run["retry_source_run_id"]:
                diagnostics["runs_with_explicit_retry_source"] += 1
                retry_sources.add(run["retry_source_run_id"])
    diagnostics["explicit_retry_sources_in_selected_runs"] = len(retry_sources & selected_runs.keys())

    # Invocations reference run_id without a workspace column. Task links below
    # must also match; a run-id join alone would cross workspace boundaries.
    for record in conn.execute("SELECT run_id FROM job_runs GROUP BY run_id HAVING COUNT(*)>1"):
        if record["run_id"] in selected_runs:
            diagnostics["selected_run_ids_repeated_across_workspaces"] += 1

    activities, recovery_runs, final_recovery_runs, implementation_counts = {}, set(), set(), Counter()
    first_invocation, last_invocation = None, None
    # Stream projected telemetry only. No token values, costs, tool payloads or prompts.
    for record in conn.execute(
        "SELECT i.id,i.ts,i.job_run_id,i.activity_id,i.duration_ms,"
        "i.provider_cost_usd IS NOT NULL AS has_cost,"
        "(SELECT json_group_array(DISTINCT t.task_id) FROM invocation_tasks t WHERE t.invocation_id=i.id) AS task_ids "
        "FROM invocations i WHERE julianday(i.ts)<julianday(?) ORDER BY i.id", (stamp(cutoff),)
    ):
        if record["job_run_id"] not in selected_runs:
            continue
        linked = set(json.loads(record["task_ids"]))
        if linked != {selected_runs[record["job_run_id"]]["task_id"]}:
            diagnostics["run_id_candidate_invocations_excluded_by_task_links"] += 1
            continue
        activity = record["activity_id"]
        if activity not in {"implement_one"} | RECOVERY:
            activity = "other"
        aggregate = activities.setdefault(activity, {"invocations": 0, "duration_ms": 0, "with_provider_cost": 0})
        aggregate["invocations"] += 1
        aggregate["duration_ms"] += record["duration_ms"]
        aggregate["with_provider_cost"] += record["has_cost"]
        at = instant(record["ts"])
        first_invocation = min(first_invocation, at) if first_invocation else at
        last_invocation = max(last_invocation, at) if last_invocation else at
        if activity == "implement_one":
            implementation_counts[record["job_run_id"]] += 1
        if activity in RECOVERY:
            recovery_runs.add(record["job_run_id"])
            if record["job_run_id"] in final_run_ids:
                final_recovery_runs.add(record["job_run_id"])
    diagnostics["selected_runs_without_implementation_invocation"] = len(selected_runs.keys() - implementation_counts.keys())
    diagnostics["final_runs_without_implementation_invocation"] = len(final_run_ids - implementation_counts.keys())
    diagnostics["final_runs_with_multiple_implementation_invocations"] = sum(implementation_counts[r] > 1 for r in final_run_ids)
    diagnostics["selected_runs_with_recovery_invocation"] = len(recovery_runs)
    diagnostics["final_runs_with_recovery_invocation"] = len(final_recovery_runs)
    diagnostics["earlier_runs_with_recovery_invocation"] = len(recovery_runs & extra_run_ids)
    for path, original in files.items():
        if fingerprint(path) != original:
            raise RuntimeError("task metadata changed during analysis; rerun")
    conn.rollback()
    conn.close()
    return {
        "schema_version": 1,
        "scope": "Constellation Works building Orbit; PR-pipeline delivery runs for first-done tasks",
        "cohort_since_inclusive": stamp(since), "cohort_until_exclusive": stamp(until),
        "observation_cutoff_exclusive": stamp(cutoff),
        "read_started_at": stamp(started), "read_finished_at": stamp(datetime.now(timezone.utc)),
        "source_revision": args.source_revision,
        "coverage": {"run_store_rows_at_read": run_rows, "task_bundles_examined": len(bindings),
                     "first_done_tasks": len(cohort), "first_done_event_types": dict(sorted(done_types.items())),
                     "exclusions": dict(sorted(exclusions.items())),
                     "selected_invocation_first": stamp(first_invocation) if first_invocation else None,
                     "selected_invocation_last": stamp(last_invocation) if last_invocation else None},
        "groups": {name: summary(items) for name, items in sorted(groups.items())},
        "delivery_run_states": dict(sorted(states.items())),
        "final_run_recorded_models": dict(sorted(models.items())),
        "invocation_activities": dict(sorted(activities.items())),
        "diagnostics": dict(sorted(diagnostics.items())),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("run-db", "task-index", "workspace", "since", "until", "cutoff", "source-revision"):
        parser.add_argument("--" + option, required=True)
    print(json.dumps(measure(parser.parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
