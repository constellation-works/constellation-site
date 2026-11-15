"""Offline analytics snapshot projection and replay checks."""

import json
import pathlib

from .common import (
    FAILURE_RATE_LABEL,
    OUTCOME_COUNTS,
    PUBLIC_KEYS,
    ROLES,
    dump,
    empty_dropped,
)
from .experiments import (
    project_experiment,
)
from .metrics import (
    project_completions,
    project_defects,
    project_durations,
)
from .rank import (
    project_rank,
)
from .redaction import (
    forbidden_patterns,
    guard,
    sanitize,
)
from .reliability import (
    project_reliability,
)
from .scorecards import (
    project_board,
    project_cells,
)
from .snapshot import (
    assemble_meta,
    replay,
    write_snapshot,
)


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
                "below_support": False, "unjudged": False, "reasoning_effort": "unknown",
                "effort_label": "effort unknown", "label": "claude-opus @ effort unknown",
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
    assert board["rows"][0]["reasoning_effort"] == "unknown" and board["rows"][0]["effort_label"] == "effort unknown"
    assert "label" not in board["rows"][0]
    assert "reasoning_effort" not in board["rows"][1] and "effort_label" not in board["rows"][1]
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
    for leaked in (
        "/srv/acme/customer.txt", "/root/acme/customer.txt", "/mnt/acme/customer.txt",
        "/data/acme/customer.txt", "/home/private/customer.txt",
        r"C:\acme\customer.txt", "C:/acme/customer.txt", r"\\server\share\customer.txt",
        "crates/core/customer.rs", "scripts/analytics_snapshot.py", "./src/lib.rs",
    ):
        cleaned = sanitize(f"check {leaked} end", patterns, redactions)
        assert leaked not in cleaned and "[redacted]" in cleaned, (leaked, cleaned)
    assert sanitize("delivered on 3/4 runs", patterns, redactions) == "delivered on 3/4 runs"
    api_source = "GET /api/diagnostics/implement_one?since=30d&outcome=succeeded"
    assert sanitize(api_source, patterns, redactions) == api_source

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
    docs["rank"] = project_rank({
        "window": "30d", "since": "2026-09-25T00:00:00Z", "until": "2026-10-25T00:00:00Z",
        "settle_lag": "14d", "execution": "managed", "live": False, "provisional": False, "status": "ok",
        "qualified": True, "scales_source": "season",
        "measures": [{"key": "escaped_regressions", "label": "Escaped regressions", "weight": 30.0, "sign": -1.0,
                      "pillar": "quality", "status": "measured", "units": "implemented tasks",
                      "definition": "See ORB-1 at /home/daniel/rank.rs", "reason": None}],
        "weights_total": 30.0,
        "rules": {"shrinkage_k": 30.0, "min_tasks": 30, "min_tiers": 2, "min_tier_tasks": 5, "interval_percentiles": [10, 90]},
        "unattributed": {"tasks": 3, "crews": [{"crew": "secret", "tasks": 3}]},
        "paired_probabilities": {"gpt-a": {"gpt-b": 0.9}},
        "rows": [
            {"model": "gpt-a", "rank": 1, "rank_label": "1", "band_size": 1, "eligible": True, "units": 40,
             "tasks_by_tier": {"low": 20, "medium": 20}, "score": 110.0, "raw_score": 112.0,
             "interval": {"p10": 105.0, "p90": 115.0}, "z": 1.0,
             "cost": {"ratio": 0.8, "per_task": 1.0, "expected_per_task": 1.25, "coverage": 0.9, "cost_unknown": False},
             "measures": {"escaped_regressions": {"status": "measured", "weight": 30.0, "units": 40, "unit": "implemented tasks",
                                                  "actual": 1.0, "expected": 2.0, "residual": 0.1, "contribution": 3.0}},
             "landed_tasks": 39.0, "landed_rate": 0.975,
             "crews": [{"crew": "sol", "tasks": 38}, {"crew": "crew unknown", "tasks": 2}],
             "effort_split": [{"crew": None, "model": "gpt-a", "provider_cost_usd": 1.0}],
             "tiers": [{"tier": "low", "tasks": 20, "score": 108.0, "cost_per_task": 0.5, "cost_coverage": 1.0, "cost_unknown": False}]},
            {"model": "model unknown", "rank": None, "eligible": False, "units": 9},
            {"model": "gpt-thin", "rank": None, "eligible": False, "ineligible_reason": "8 implemented tasks; 30 needed",
             "units": 8, "tasks_by_tier": {"hard": 8}, "score": 120.0, "interval": None},
        ],
    }, dropped, patterns, redactions)
    assert [row["model"] for row in docs["rank"]["rows"]] == ["gpt-a", "gpt-thin"]
    assert docs["rank"]["rows"][0]["crews"] == [{"crew": "sol", "tasks": 38}]
    assert "paired_probabilities" not in docs["rank"] and "effort_split" not in docs["rank"]["rows"][0]
    assert "ORB-1" not in docs["rank"]["measures"][0]["definition"]
    assert dropped["rank"] == 2
    assert docs["rank"]["live"] is False and docs["rank"]["provisional"] is False
    assert docs["rank"]["settle_lag"] == "14d"
    assert docs["rank"]["window"] == {"key": "30d", "since": "2026-09-25T00:00:00Z", "until": "2026-10-25T00:00:00Z"}
    assert docs["rank"]["scales_source"] == "season" and docs["rank"]["qualified"] is True
    assert "live=" not in docs["rank"]["source"]
    assert docs["rank"]["rows"][1]["ineligible_reason"] == "8 implemented tasks; 30 needed"
    assert docs["rank"]["eligibility_rule"].startswith("At least 30 implemented tasks")
    try:
        project_rank({"window": "30d", "execution": "managed", "live": True, "provisional": True}, empty_dropped(), patterns, [0])
    except SystemExit:
        pass
    else:
        raise SystemExit("project_rank accepted a live board")
    docs["meta"] = assemble_meta(docs, "2026-11-08T00:00:00Z", "0.47.0", "orbit", False, dropped, redactions[0])
    assert docs["meta"]["windows"]["rank"]["key"] == "30d"
    assert "reviewers_settled" not in docs["meta"]["dropped"]
    assert docs["meta"]["reviewer_settled"] is False
    assert docs["scorecards"]["reviewers"]["provisional"]["provisional"] is True
    guard(docs, hosts)
    tampered = json.loads(dump(docs))
    tampered["experiments"]["experiments"][0]["hypothesis"] = "Investigate /srv/acme/customer.txt"
    try:
        guard(tampered, hosts)
    except SystemExit:
        pass
    else:
        raise SystemExit("guard accepted an unlisted absolute path")
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
