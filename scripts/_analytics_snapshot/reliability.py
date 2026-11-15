"""Fleet reliability aggregate projections."""

import collections

from .common import (
    FAILURE_RATE_LABEL,
    MIN_CONFIDENT_SAMPLE,
    OUTCOME_COUNTS,
    SAFE_KEY,
    SAFE_LABEL,
    SAFE_TOKEN,
    WINDOW,
    is_number,
    whole,
)


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
