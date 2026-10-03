#!/usr/bin/env python3
"""Classify failed agent delivery runs and count problems found after successful ones.

Reads one Orbit workspace's run store and task index read-only and prints aggregate JSON.
No task text, prompts, logs, paths or identities are printed; see method.md.

Population: leaf delivery runs (`task_pr_pipeline`, `task_local_pipeline`) created in
[--since, --until) that reached a terminal state. Wrapper pipelines are not counted.

Each failed run is classified from the error message of its failed step by the first
matching rule in RULES. The rules are ordered; the order is part of the method.

After success: tasks delivered by a successful run in the window, and how many of them are
the target of a `regression_from` relation from a task created before --cutoff.

Usage:
  python3 -B measure.py --run-db DB --task-index INDEX --workspace BINDING \
      --since 2026-07-06T00:00:00Z --until 2026-10-01T00:00:00Z --cutoff 2026-10-01T00:00:00Z
"""

import argparse
import collections
import datetime
import json
import os
import re
import sqlite3
import sys

LEAF = ("task_pr_pipeline", "task_local_pipeline")
TERMINAL = ("success", "failed", "cancelled", "interrupted", "timeout", "skipped")

# (category, group, pattern). First match wins.
RULES = [
    ("agent_declared_failure", "agent_stopped",
     r'envelope status="(failed|timeout)"|execution_summary begins with \'Outcome: failed\''),
    ("no_change_to_ship", "nothing_to_change",
     r"nothing to commit|no staged changes to commit"),
    ("change_rejected_by_review", "change_rejected",
     r"review_gate_blocked|independent review did not succeed"),
    ("missing_handoff_summary", "agent_process",
     r"requires a meaningful persisted execution_summary"),
    ("agent_process_ended", "agent_process",
     r"provider exited|exited with code|wall-clock timeout|agent protocol violation"),
    ("checkout_changed_during_run", "concurrent_work",
     r"primary_checkout_drift|worktree_integrity_ambiguous|worktree_head_changed"),
    ("conflict_or_stale_base", "concurrent_work",
     r"conflict|is behind base|must be ahead of and not behind|moved from checkpoint"),
    ("host_or_repository_setup", "machine",
     r"failed to spawn|Bubblewrap|write-grant anchor|snapshot Git state|squash merge|"
     r"Squash merges|merge method|auto-merge|TLS handshake|git fetch|git push failed|"
     r"untracked paths|not permitted by"),
    ("orbit_defect", "machine", r"."),
]
COMPILED = [(c, g, re.compile(p)) for c, g, p in RULES]

# Themes for the codes agents gave when they declared failure. Codes are free text chosen
# by the agent; any code not listed here is reported as "other".
CODE_THEMES = {
    "could_not_verify_here": [
        "validation_blocked", "validation_blocker", "validation_incomplete", "validation_timeout",
        "validation_environment_unavailable", "native_validation_environment_unavailable",
        "security_validation_unavailable", "codeql_unavailable", "macos_reproduction_unavailable",
        "live_enforcement_unavailable", "live_enforcement_unproved",
        "insufficient_runner_evidence", "post_merge_validation_required"],
    "checks_failed": [
        "validation_failed", "validation_gate_failed", "full_workspace_validation_failed"],
    "not_finished": [
        "implementation_incomplete", "incomplete_implementation", "review_incomplete",
        "recovery_integrity_incomplete", "proof_contract_unresolved"],
    "task_needs_a_decision": [
        "scope_ambiguity", "scope_contradiction", "scope_boundary_ambiguous",
        "preparation_requirement_conflict", "already_covered_by_other_task",
        "duplicate_already_covered", "dependency_blocked", "enforcement_design_blocked",
        "blocked_awaiting_decision", "invalid_task_record", "recovery_prerequisite_blocked"],
    "not_permitted": [
        "cleanup_blocked", "cleanup_denied", "runner_permission_denied",
        "environment_write_restricted", "orbit_task_update_unavailable", "task_state_read_only",
        "operator_publication_required", "missing_sweep_cursor", "worktree_mismatch"],
}
THEME_OF = {code: theme for theme, codes in CODE_THEMES.items() for code in codes}

# Tags that mark a finding filed by a review or QA sweep.
REVIEW_TAGS = {"code-review", "qa-sweep", "full-review", "security-review"}

# Tags that mark a task filed by an automated alert sweep.
SWEEP_TAGS = {"code-scanning-sweep", "ci-failure-sweep", "dependabot-sweep"}


def classify(message):
    for category, group, pattern in COMPILED:
        if pattern.search(message):
            return category, group


def iso(value):
    """Normalise an ISO timestamp for comparison (UTC, microseconds)."""
    text = value.strip().replace("Z", "+00:00").replace(" ", "T")
    m = re.match(r"(.*T\d\d:\d\d:\d\d)(\.\d+)?([+-]\d\d:\d\d)$", text)
    if not m:
        raise ValueError(f"unparseable timestamp {value!r}")
    frac = (m.group(2) or ".0")[:7].ljust(7, "0")
    dt = datetime.datetime.fromisoformat(m.group(1) + frac + m.group(3))
    return dt.astimezone(datetime.timezone.utc)


def read_status(bundle):
    with open(os.path.join(bundle, "task.yaml"), encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("status:"):
                return line.split(":", 1)[1].strip().strip("'\"")
    return None


def read_done_after(bundle, after):
    """First event moving the task to done at or after `after`, else None."""
    path = os.path.join(bundle, "events.jsonl")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            event = json.loads(line)
            if event.get("to_status") == "done" and iso(event["at"]) >= after:
                return iso(event["at"])
    return None


def median(values):
    values = sorted(values)
    if not values:
        return None
    n = len(values)
    return values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2


def connect(path):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    return db


def measure(args):
    since, until, cutoff = iso(args.since), iso(args.until), iso(args.cutoff)
    runs_db, index = connect(args.run_db), connect(args.task_index)
    started = datetime.datetime.now(datetime.timezone.utc)

    runs = []
    for run_id, job_id, state, created, input_json in runs_db.execute(
            "SELECT run_id, job_id, state, created_at, input_json FROM job_runs "
            "WHERE workspace_id=? AND job_id IN (?, ?)", (args.workspace, *LEAF)):
        at = iso(created)
        if not (since <= at < until) or state not in TERMINAL:
            continue
        tasks = json.loads(input_json or "{}").get("task_ids") or []
        review = bool(json.loads(input_json or "{}").get("review"))
        runs.append({"run_id": run_id, "job": job_id, "state": state, "at": at, "tasks": tasks,
                     "review": review})

    steps = collections.defaultdict(list)
    for run_id, idx, state, message in runs_db.execute(
            "SELECT run_id, step_index, state, error_message FROM job_run_steps "
            "WHERE workspace_id=? ORDER BY run_id, step_index", (args.workspace,)):
        if state == "failed":
            steps[run_id].append(message or "")

    bundles = dict(index.execute(
        "SELECT task_id, canonical_path FROM task_bundle_bindings WHERE workspace_id=?",
        (args.workspace,)))
    created = {t: iso(c) for t, c in index.execute(
        "SELECT task_id, created_at FROM task_bundle_index WHERE workspace_id=?",
        (args.workspace,))}
    tags = collections.defaultdict(set)
    for task, tag in index.execute(
            "SELECT task_id, tag FROM task_bundle_tags WHERE workspace_id=?", (args.workspace,)):
        tags[task].add(tag)
    filed = collections.defaultdict(collections.Counter)
    for task, at in created.items():
        if since <= at < until:
            month = at.strftime("%Y-%m")
            if tags[task] & REVIEW_TAGS:
                filed["review_findings"][month] += 1
            if "ci-failure-sweep" in tags[task]:
                filed["ci_failure_repairs"][month] += 1
    regression_reports = collections.defaultdict(set)
    for source, target in index.execute(
            "SELECT source_task_id, target_task_id FROM task_bundle_relations "
            "WHERE workspace_id=? AND relation_type='regression_from'", (args.workspace,)):
        if source in created and created[source] < cutoff:
            regression_reports[target].add(source)
    for source in {s for reports in regression_reports.values() for s in reports}:
        if since <= created[source] < until:
            filed["regression_reports"][created[source].strftime("%Y-%m")] += 1

    states = collections.Counter(r["state"] for r in runs)
    months = collections.defaultdict(collections.Counter)
    categories, groups = collections.Counter(), collections.Counter()
    by_month = collections.defaultdict(collections.Counter)
    declared_codes, declared_themes = collections.Counter(), collections.Counter()
    sweep_tasks = collections.Counter()
    failed_tasks = collections.defaultdict(list)  # task -> [(time, category)]
    unclassified = 0
    for r in runs:
        months[r["at"].strftime("%Y-%m")][r["state"]] += 1
        if r["state"] != "failed":
            continue
        messages = steps.get(r["run_id"]) or [""]
        if not steps.get(r["run_id"]):
            unclassified += 1
        category, group = classify(messages[0])
        categories[category] += 1
        groups[group] += 1
        by_month[category][r["at"].strftime("%Y-%m")] += 1
        if category == "agent_declared_failure":
            code = re.search(r"error\.code=(\w+)", messages[0])
            code = code.group(1) if code else None
            declared_codes[code or "(none given)"] += 1
            declared_themes[THEME_OF.get(code, "other") if code else "no_code_given"] += 1
        if any(tags[t] & SWEEP_TAGS for t in r["tasks"]):
            sweep_tasks[category] += 1
        for task in r["tasks"]:
            failed_tasks[task].append((r["at"], category))

    delivered = {t for r in runs if r["state"] == "success" for t in r["tasks"]}
    regressed = {t for t in delivered if regression_reports.get(t)}
    reviewed_runs = [r for r in runs if r["review"]]
    delivered_reviewed = {t for r in reviewed_runs if r["state"] == "success" for t in r["tasks"]}
    delivered_by_month = collections.Counter()
    regressed_by_month = collections.Counter()
    last_success = {}
    for r in runs:
        if r["state"] == "success":
            for t in r["tasks"]:
                last_success[t] = max(last_success.get(t, r["at"]), r["at"])
    for t, at in last_success.items():
        delivered_by_month[at.strftime("%Y-%m")] += 1
        if t in regressed:
            regressed_by_month[at.strftime("%Y-%m")] += 1

    # What happened to tasks after their first failed run in the window.
    after = collections.defaultdict(collections.Counter)
    hours_to_done = collections.defaultdict(list)
    for task, failures in failed_tasks.items():
        first_at, category = min(failures)
        bundle = bundles.get(task)
        if not bundle:
            after[category]["task_record_missing"] += 1
            continue
        done_at = read_done_after(bundle, first_at)
        if done_at and done_at < cutoff:
            later_success = any(r["state"] == "success" and task in r["tasks"]
                                and r["at"] > first_at for r in runs)
            after[category]["done_via_later_successful_run" if later_success
                            else "done_without_successful_run"] += 1
            hours_to_done[category].append((done_at - first_at).total_seconds() / 3600)
        else:
            after[category]["not_done_by_cutoff:" + (read_status(bundle) or "unknown")] += 1

    finished = len(runs)
    return {
        "schema_version": 1,
        "scope": "Constellation Works building Orbit: leaf delivery runs in Orbit's own repository",
        "window_since_inclusive": args.since,
        "window_until_exclusive": args.until,
        "observation_cutoff_exclusive": args.cutoff,
        "read_started_at": started.isoformat(),
        "runs": {
            "finished": finished,
            "by_state": dict(states),
            "by_pipeline": dict(collections.Counter(r["job"] for r in runs)),
            "runs_not_single_task": sum(len(r["tasks"]) != 1 for r in runs),
            "with_review_step": len(reviewed_runs),
            "with_review_step_by_state": dict(collections.Counter(r["state"] for r in reviewed_runs)),
            "with_review_step_by_month": dict(sorted(collections.Counter(
                r["at"].strftime("%Y-%m") for r in reviewed_runs).items())),
            "by_month": {m: dict(c) for m, c in sorted(months.items())},
        },
        "failed": {
            "total": states["failed"],
            "without_failed_step_message": unclassified,
            "by_group": dict(groups.most_common()),
            "by_category": dict(categories.most_common()),
            "by_category_and_month": {k: dict(sorted(v.items())) for k, v in by_month.items()},
            "agent_declared_themes": dict(declared_themes.most_common()),
            "agent_declared_codes": dict(declared_codes.most_common()),
            "agent_declared_distinct_codes": len([c for c in declared_codes if c != "(none given)"]),
            "runs_whose_task_came_from_an_alert_sweep_by_category": dict(sweep_tasks.most_common()),
            "tasks_with_a_failed_run": len(failed_tasks),
            "after_first_failure_by_category": {k: dict(v) for k, v in after.items()},
            "median_hours_first_failure_to_done_by_category": {
                k: round(median(v), 2) for k, v in hours_to_done.items()},
        },
        "after_success": {
            "tasks_delivered": len(delivered),
            "tasks_with_regression_report": len(regressed),
            "regression_reports_against_delivered_tasks": sum(
                len(regression_reports[t]) for t in regressed),
            "tasks_delivered_by_a_reviewed_run": len(delivered_reviewed),
            "of_those_with_regression_report": len(delivered_reviewed & regressed),
            "delivered_by_month_of_last_success": dict(sorted(delivered_by_month.items())),
            "regressed_by_month_of_last_success": dict(sorted(regressed_by_month.items())),
        },
        "tasks_filed_in_window_by_month": {k: dict(sorted(v.items())) for k, v in filed.items()},
        "rules": [{"category": c, "group": g, "pattern": p} for c, g, p in RULES],
        "code_themes": CODE_THEMES,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for flag in ("--run-db", "--task-index", "--workspace", "--since", "--until", "--cutoff"):
        p.add_argument(flag, required=True)
    json.dump(measure(p.parse_args()), sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
