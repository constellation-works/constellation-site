"""The public /ranking/ page (model rank, overall index, crews by role) rendered from a snapshot."""

import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("site_build", ROOT / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def window(since, until, key="30d"):
    return {"key": key, "since": since, "until": until}


def board(unit, rows, since="2026-10-01T00:00:00Z", until="2026-10-31T00:00:00Z", **extra):
    payload = {
        "min_support": 10,
        "role": "implementers",
        "rows": rows,
        "score_key": f"Score: per 100 {unit}, credit for landed; debits for rework. The fleet average is 100.0.",
        "unit": unit,
        "window": window(since, until),
    }
    payload.update(extra)
    return payload


def row(crew, model, units, rank, score):
    return {
        "below_support": units < 10,
        "crew": crew,
        "model": model,
        "rank": rank,
        "score": score,
        "units": units,
    }


def scorecards():
    return {
        "implementers": board(
            "implemented tasks",
            [
                row("haiku", "claude-haiku-5-5", 30, 1, 146.38),
                row("tiny", "gpt-tiny", 9, 1, 200),
                row("crew unavailable", "claude-haiku-5-5", 40, 2, 10),
                row("legacy", "model unknown", 40, 3, 10),
                row("crew unknown", "gpt-6-luna", 40, 4, 10),
            ],
        ),
        "implementers_by_tier": {
            "cells": [
                {"below_support": True, "crew": "haiku", "crew_mean": 110, "model": "claude-haiku-5-5",
                 "n": 6, "rank": None, "tier": "low", "type": "docs", "units": 6},
                {"below_support": True, "crew": "haiku", "crew_mean": 110, "model": "claude-haiku-5-5",
                 "n": 6, "rank": None, "tier": "low", "type": "ui", "units": 6},
                {"below_support": False, "crew": "opus", "crew_mean": 140, "model": "claude-opus-5-5",
                 "n": 10, "rank": 1, "tier": "low", "type": "ui", "units": 10},
                {"below_support": True, "crew": "thin", "crew_mean": 180, "model": "gpt-thin",
                 "n": 3, "rank": None, "tier": "low", "type": "ui", "units": 3},
                {"below_support": False, "crew": "gap", "crew_mean": 999, "model": "model unknown",
                 "n": 50, "rank": 1, "tier": "low", "type": "ui", "units": 50},
            ],
            "min_support": 10,
            "unit": "tasks",
            "window": window("2026-10-09T09:11:25Z", "2026-11-08T09:11:25Z"),
        },
        "pilots": board(
            "assessed tasks",
            [row("haiku", "claude-haiku-5-5", 20, 1, 47.94)],
            since="2026-10-09T09:11:48Z",
            until="2026-11-08T09:11:48Z",
        ),
        "reviewers": {
            "provisional": board(
                "settled reviews",
                [row("opus", "claude-opus-5-5", 18, 1, 231.74)],
                since="2026-10-09T09:11:36Z",
                until="2026-11-08T09:11:36Z",
                provisional_units=1387,
            ),
            "settled": board(
                "settled reviews",
                [row("luna", "gpt-6-luna", 214, 1, 71.56)],
                since="2026-09-09T09:11:48Z",
                until="2026-10-09T09:11:48Z",
            ),
        },
        "orchestrators": board("attempts", [row("orchestrator-only", "secret-model", 99, 1, 1)]),
    }


def effort_row(crew, model, effort, units, rank, score, estimate=None):
    """A scorecard row split by effort, as the exporter writes it since ORB-23657."""
    out = row(crew, model, units, rank, score)
    out["reasoning_effort"] = effort
    out["effort_label"] = "effort unknown" if effort == "unknown" else effort
    if estimate is not None:
        out["effort_estimate"] = estimate
    return out


def effort_cell(crew, model, effort, n, crew_mean, tier="low", kind="ui", estimate=None):
    cell = {"below_support": n < 10, "crew": crew, "crew_mean": crew_mean, "model": model, "n": n,
            "rank": None, "tier": tier, "type": kind, "units": n, "reasoning_effort": effort,
            "effort_label": "effort unknown" if effort == "unknown" else effort}
    if estimate is not None:
        cell["effort_estimate"] = estimate
    return cell


def effort_scorecards():
    """Two efforts of one crew (sol) on every board.

    sol's unrecorded rows carry an effort_estimate, as snapshots written before
    ORB-23846 do; it is ignored, so they read sol · effort unknown beside sol@high.
    argon's unrecorded rows read argon · effort unknown; haiku@high already names its effort.
    """
    data = scorecards()
    data["implementers"]["rows"] = [
        effort_row("sol", "gpt-6.1-sol", "unknown", 30, 1, 132.6, estimate="high"),
        effort_row("sol", "gpt-6.1-sol", "high", 20, 2, 115.5),
        effort_row("opus", "claude-opus-5-5", "medium", 15, 3, 90.0),
        effort_row("haiku@high", "claude-haiku-5-5", "high", 12, 4, 85.0),
        effort_row("argon", "gemini-4-argon-high", "unknown", 11, 5, 80.0),
        effort_row("sol", "gpt-6.1-sol", "xhigh", 4, None, 140.0),
    ]
    data["implementers"]["fleet_average"] = 110.0
    data["implementers_by_tier"]["cells"] = [
        effort_cell("sol", "gpt-6.1-sol", "unknown", 10, 130.0, estimate="high"),
        effort_cell("sol", "gpt-6.1-sol", "high", 12, 120.0),
        effort_cell("opus", "claude-opus-5-5", "medium", 10, 80.0),
        effort_cell("sol", "gpt-6.1-sol", "high", 11, 125.0, tier="medium"),
        effort_cell("sol", "gpt-6.1-sol", "unknown", 10, 105.0, tier="medium", estimate="high"),
    ]
    data["reviewers"]["provisional"]["rows"] = [
        effort_row("sol", "gpt-6.1-sol", "unknown", 15, 1, 130.0, estimate="high"),
        effort_row("sol", "gpt-6.1-sol", "high", 12, 2, 90.0),
        effort_row("opus", "claude-opus-5-5", "medium", 11, 3, 80.0),
    ]
    data["reviewers"]["provisional"]["fleet_average"] = 100.0
    data["reviewers"]["settled"]["rows"] = [
        effort_row("sol", "gpt-6.1-sol", "unknown", 15, 1, 120.0, estimate="high"),
        effort_row("sol", "gpt-6.1-sol", "high", 12, 2, 95.0),
    ]
    data["pilots"]["rows"] = [
        effort_row("sol", "gpt-6.1-sol", "high", 12, 1, 60.0),
        effort_row("sol", "gpt-6.1-sol", "unknown", 11, 2, 40.0, estimate="high"),
        effort_row("opus", "claude-opus-5-5", "medium", 10, 3, 30.0),
    ]
    data["pilots"]["fleet_average"] = 45.0
    return data


def board_crews(html_text):
    """Each crew cell on a board as plain text: (crew with effort, model)."""
    found = re.findall(r'<span class="crew-id"><span class="crew-name">(.*?)</span><span class="crew-model">(.*?)</span></span>',
                       html_text)
    return [(re.sub(r"<[^>]+>", "", name), model) for name, model in found]


def plain(html_text):
    return re.sub(r"<[^>]+>", "", html_text)


def rank_measure(weight, contribution=None, reason=None):
    measured = contribution is not None
    return {
        "actual": 1.0 if measured else None, "contribution": contribution, "expected": 2.0 if measured else None,
        "reason": reason, "residual": 0.1 if measured else None, "status": "measured" if measured else "unmeasured",
        "unit": "implemented tasks", "units": 40 if measured else 0, "weight": weight,
    }


def rank_row(model, rank, label, score, units, crews, eligible=True, reason=None):
    return {
        "band_size": 1 if eligible else None, "eligible": eligible, "ineligible_reason": reason,
        "model": model, "rank": rank, "rank_label": label, "score": score, "raw_score": score,
        "units": units, "interval": {"p10": score - 4, "p90": score + 4} if eligible else None,
        "cost": {"cost_unknown": False, "coverage": 0.9, "expected_per_task": 2.0, "per_task": 1.5, "ratio": 0.75},
        "crews": [{"crew": crew, "tasks": units} for crew in crews],
        "landed_rate": 0.97, "landed_tasks": units * 0.97,
        "measures": {"escaped_regressions": rank_measure(30, 4.2), "tool_call_errors": rank_measure(5, reason="not attributed yet")},
        "tasks_by_tier": {"low": units // 2, "medium": units - units // 2},
        "tiers": [{"tier": "low", "tasks": units // 2, "score": score, "cost_per_task": 1.2, "cost_coverage": 1.0, "cost_unknown": False},
                  {"tier": "medium", "tasks": units - units // 2, "score": score, "cost_per_task": 1.8, "cost_coverage": 0.8, "cost_unknown": False}],
        "weights_measured": 30.0,
    }


def rank_board():
    """A live rank.json, as the snapshot writes it since ORB-23668."""
    return {
        "computed_at": "2026-11-08T06:00:00Z", "eligible_models": 3, "execution": "managed",
        "live": True, "provisional": True,
        "eligibility_rule": "Orbit fixture rule: 30 tasks in one tier of 5+.",
        "window": window("2026-10-09T06:00:00Z", "2026-11-08T06:00:00Z"),
        "measures": [
            {"key": "escaped_regressions", "label": "Escaped regressions", "pillar": "quality", "reason": None,
             "sign": -1.0, "status": "measured", "units": "implemented tasks", "weight": 30.0,
             "definition": "Escaped regressions against the tier expectation."},
            {"key": "tool_call_errors", "label": "Tool-call errors", "pillar": "reliability", "reason": "not attributed yet",
             "sign": -1.0, "status": "unmeasured", "units": "tool calls", "weight": 5.0,
             "definition": "Tool calls classed expected or denied."},
        ],
        "weights_total": 35.0,
        "not_scored": {"count": 12, "reasons": {"no_cause": 12}},
        "rules": {"shrinkage_k": 30, "min_tasks": 30, "min_tiers": 2, "min_tier_tasks": 5,
                  "min_eligible_models": 3, "band_probability": 0.8, "draws": 1000},
        "rows": [
            rank_row("claude-haiku-5-5", 1, "1", 120.0, 60, ["haiku"]),
            rank_row("claude-opus-5-5", 2, "2", 104.0, 50, ["opus"]),
            rank_row("gpt-6-luna", 3, "3", 90.0, 40, ["luna"]),
            rank_row("gpt-tiny", None, None, 130.0, 9, ["tiny"], eligible=False, reason="Orbit says: 9 of 30 tasks so far"),
            rank_row("model unknown", None, None, 100.0, 50, ["gap"], eligible=False, reason="gap"),
        ],
    }


def all_roles_scorecards():
    """Models across the three roles, fleet average 100 on every board.

    model-ir: implementer 120, reviewer 80. model-ip: implementer 90, pilot 150.
    model-rp: reviewer 110, pilot 50. model-all: 100 in every role.
    model-i and model-r hold one role each.
    """
    data = scorecards()
    data["implementers"]["rows"] = [
        row("ir", "model-ir", 30, 1, 120.0), row("ip", "model-ip", 20, 2, 90.0),
        row("all", "model-all", 15, 3, 100.0), row("i", "model-i", 40, 4, 200.0),
    ]
    data["implementers"]["fleet_average"] = 100.0
    data["reviewers"]["provisional"]["rows"] = [
        row("ir", "model-ir", 12, 1, 80.0), row("rp", "model-rp", 14, 2, 110.0),
        row("all", "model-all", 11, 3, 100.0), row("r", "model-r", 30, 4, 300.0),
    ]
    data["reviewers"]["provisional"]["fleet_average"] = 100.0
    data["pilots"]["rows"] = [
        row("ip", "model-ip", 12, 1, 150.0), row("rp", "model-rp", 13, 2, 50.0), row("all", "model-all", 10, 3, 100.0),
    ]
    data["pilots"]["fleet_average"] = 100.0
    return data


def section(doc, element_id):
    marker = f'id="{element_id}"'
    start = doc.index(marker)
    nxt = doc.find('<section class="board"', start + len(marker))
    return doc[start:] if nxt < 0 else doc[start:nxt]


def workflow_event_section(workflow, event):
    match = re.search(
        rf"(?ms)^  {re.escape(event)}:\n(.*?)(?=^  [a-z][a-z0-9_-]*:\n|\Z)",
        workflow,
    )
    if not match:
        raise AssertionError(f"workflow has no {event} event")
    return match.group(1)


def workflow_paths(workflow, event):
    event_section = workflow_event_section(workflow, event)
    match = re.search(r"(?m)^    paths:\n((?:^      - .+\n)+)", event_section)
    if not match:
        raise AssertionError(f"workflow {event} event has no path filters")
    return [
        line.strip()[2:].strip().strip('"')
        for line in match.group(1).splitlines()
    ]


def github_path_matches(pattern, path):
    # The workflow's patterns use only literal characters, * and **. A single
    # star stays within one path segment; a double star can cross directories.
    regex = re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return re.fullmatch(regex, path) is not None


def workflow_job_condition(workflow, job):
    match = re.search(
        rf"(?ms)^  {re.escape(job)}:\n(.*?)(?=^  [a-z][a-z0-9_-]*:\n|\Z)",
        workflow,
    )
    if not match:
        raise AssertionError(f"workflow has no {job} job")
    condition = re.search(r"(?m)^    if: (.+)$", match.group(1))
    if not condition:
        raise AssertionError(f"workflow {job} job has no condition")
    return condition.group(1)


class RankingPageTest(unittest.TestCase):
    def test_whisker_axis_normal_range(self):
        rows = rank_board()["rows"][:3]
        low, high, ticks = build.whisker_axis(rows)
        self.assertLessEqual(low, min(row["interval"]["p10"] for row in rows))
        self.assertGreaterEqual(high, max(row["interval"]["p90"] for row in rows))
        self.assertTrue(3 <= len(ticks) <= 7)
        self.assertIn(100, ticks)

    def test_whisker_axis_far_off_model_keeps_other_intervals_on_scale(self):
        # The 2026-11-15 snapshot as first published, frozen so re-published data cannot move these numbers.
        rank = json.loads((ROOT / "tests/fixtures/rank-far-off-model.json").read_text())
        rows, _ = build.rank_rows(rank)
        low, high, ticks = build.whisker_axis(rows)
        self.assertLessEqual(len(ticks), 7)
        self.assertIn(100, ticks)
        self.assertLess(high - low, 150)
        for row in rows:
            if row["model"] == "muse-wonder-full-1.0":
                self.assertLess(row["score"], low)
                self.assertLess(row["interval"]["p90"], low)
            else:
                self.assertLessEqual(low, row["interval"]["p10"], row["model"])
                self.assertGreaterEqual(high, row["interval"]["p90"], row["model"])

        doc = build.models_board(rank)
        labels = re.findall(r'<span style="left:([^%]+)%">([^<]+)</span>', doc)
        self.assertEqual([label for _, label in labels], [str(tick) for tick in ticks])
        grids = re.findall(r'<span class="whisker-grid" aria-hidden="true">(.*?)</span></span>', doc)
        self.assertEqual(len(grids), len(rows))
        for grid in grids:
            self.assertEqual(re.findall(r'left:([^%]+)%', grid), [pos for pos, _ in labels])
        self.assertEqual(doc.count('class="whisker-offscale is-low"'), 1)
        self.assertNotIn('class="whisker-offscale is-high"', doc)
        outlier = doc[doc.index('>muse-wonder-full-1.0</span>'):]
        self.assertIn('<span class="ml-score">−83.9</span>', outlier)
        self.assertIn('class="whisker-point prov-muse" style="left:0.00%"', outlier)
        self.assertIn('class="sr-only">p10 −161.5 to p90 −3.0</span>', outlier)
        self.assertIn('p10–p90 interval: −161.5 to −3.0.', outlier)

    def test_whisker_axis_clips_interval_tails_and_point_independently(self):
        rank = rank_board()
        rank["rows"] = [rank_row(f"model-{i}", i + 1, str(i + 1), 90 + i * 2, 50, ["sol"])
                        for i in range(10)]
        rank["rows"][1]["interval"] = {"p10": -1000, "p90": 1000}
        rank["rows"][2]["score"] = 200
        low, high, ticks = build.whisker_axis(rank["rows"])
        self.assertGreater(low, -1000)
        self.assertLess(high, 1000)
        doc = build.models_board(rank)
        self.assertIn('class="whisker-offscale is-low"', doc)
        self.assertIn('class="whisker-offscale is-high"', doc)
        self.assertIn('left:0.00%;width:100.00%', doc)
        self.assertIn('p10 −1000.0 to p90 1000.0', doc)
        self.assertEqual(doc.count('class="whisker-offscale is-high"'), 2)
        self.assertIn('class="whisker-point prov-other" style="left:100.00%"', doc)
        self.assertIn(100, ticks)

    def test_whisker_axis_tick_budget_across_ranges(self):
        for scale in (1, 10, 100, 10000, 1000000):
            with self.subTest(scale=scale):
                rows = [{"score": score * scale} for score in (-50, 0, 50, 100, 150)]
                low, high, ticks = build.whisker_axis(rows)
                self.assertTrue(1 <= len(ticks) <= 7)
                self.assertIn(100, ticks)
                self.assertTrue(all(low <= tick <= high for tick in ticks))
                gap = (ticks[1] - ticks[0]) / (high - low) * 240
                width = max(len(build.whisker_tick_label(tick)) for tick in ticks) * 6.5
                self.assertGreaterEqual(gap, width + 12)

    def test_snapshot_picker_keeps_concise_value_beside_label(self):
        picker = build.analytics_page.snapshot_picker(
            "agents",
            {"date": "2026-11-08", "since": "2026-10-09T00:00:00Z", "until": "2026-11-08T00:00:00Z"},
            [{"month": "2026-10", "date": "2026-10-31", "since": "2026-10-01T00:00:00Z", "until": "2026-10-31T00:00:00Z"}],
        )
        self.assertIn('class="snapshot-picker-label">Snapshot</span><ul>', picker)
        self.assertIn("Latest · <time datetime=\"2026-11-08\">2026-11-08</time>", picker)
        self.assertIn(
            'title="Latest snapshot 2026-11-08, fleet reliability reference window '
            '2026-10-09 to 2026-11-08 (each board shows its own observation window)"',
            picker,
        )
        self.assertNotIn("snapshot-detail", picker)

    def test_summary_and_descriptions_allow_earlier_settled_window(self):
        data = scorecards()
        self.assertLess(
            data["reviewers"]["settled"]["window"]["until"],
            data["reviewers"]["provisional"]["window"]["until"],
        )
        doc = build.render_ranking_page(data, "2026-11-08", weekly=())
        # The settled reviewer board keeps its own, earlier window; the eyebrow
        # names the newest snapshot's 30-day window only.
        self.assertIn("2026-09-09T09:11:48Z", section(doc, "reviewers-settled"))
        eyebrow = re.search(r'<p class="eyebrow">(.*?)</p>', doc).group(1)
        plain = re.sub(r"<[^>]+>", "", eyebrow)
        self.assertEqual(plain, "Snapshot 2026-11-08 · last 30 days · Oct 1 – Oct 31 UTC")
        self.assertIn('datetime="2026-10-01T00:00:00Z"', eyebrow)
        for attribute in ('name="description"', 'property="og:description"'):
            self.assertRegex(doc, rf'<meta {attribute} content="Which models Orbit can trust')

    def test_website_workflow_routes_analytics_snapshot_changes(self):
        workflow = (ROOT / ".github" / "workflows" / "website.yml").read_text(
            encoding="utf-8"
        )
        analytics_inputs = (
            "data/analytics/2026-11-08/scorecards.json",
            "data/analytics/2026-11-08/metrics.json",
            "data/analytics/2026-11-08/reliability.json",
        )
        existing_inputs = (
            "public/index.html",
            "notes/example/index.md",
            "build.py",
            "wrangler.toml",
            ".github/workflows/website.yml",
            ".github/requirements/website.txt",
        )
        unrelated_inputs = (
            "README.md",
            "unrelated/file.txt",
        )

        for event in ("pull_request", "push"):
            patterns = workflow_paths(workflow, event)

            def matches_any(path):
                return any(github_path_matches(pattern, path) for pattern in patterns)

            for path in analytics_inputs:
                self.assertTrue(
                    matches_any(path),
                    f"{event} does not select build input {path}",
                )
            for path in existing_inputs:
                self.assertTrue(matches_any(path), f"{event} no longer selects {path}")
            for path in unrelated_inputs:
                self.assertFalse(matches_any(path), f"{event} unexpectedly selects {path}")

        self.assertRegex(
            workflow_event_section(workflow, "push"),
            r"(?m)^    branches: \[main\]$",
        )
        self.assertEqual(
            workflow_job_condition(workflow, "build"),
            "github.event_name == 'pull_request'",
        )
        self.assertEqual(
            workflow_job_condition(workflow, "publish"),
            "github.event_name != 'pull_request' && github.ref == 'refs/heads/main'",
        )

    def test_analytics_automerge_dispatches_website_publish(self):
        automerge = (ROOT / ".github" / "workflows" / "analytics-automerge.yml").read_text(
            encoding="utf-8"
        )
        website = (ROOT / ".github" / "workflows" / "website.yml").read_text(
            encoding="utf-8"
        )

        # The merge is still armed with the run's GITHUB_TOKEN, so the push to
        # main it produces starts no workflow runs.
        self.assertIn("GH_TOKEN: ${{ github.token }}", automerge)
        self.assertRegex(automerge, r"(?m)^\s+gh pr merge .*--auto --squash")
        self.assertIn('--match-head-commit "$HEAD_SHA"', automerge)

        # A pull_request closed run cannot be the delivery path: events created
        # with GITHUB_TOKEN (other than workflow_dispatch/repository_dispatch)
        # create no runs, so a closed trigger would never fire for these
        # merges. The dispatch must live in the arming run instead.
        self.assertIn(
            "types: [opened, reopened, synchronize, ready_for_review]", automerge
        )

        # The automerge job can dispatch workflows (workflow_dispatch always
        # creates a run, even from GITHUB_TOKEN) alongside its merge scoping.
        job = re.search(
            r"(?ms)^  automerge:\n(.*?)(?=^  [a-z][a-z0-9_-]*:\n|\Z)", automerge
        )
        self.assertIsNotNone(job, "automerge workflow has no automerge job")
        for permission in ("contents: write", "pull-requests: write", "actions: write"):
            self.assertIn(permission, job.group(1))

        # The dispatch targets website.yml on main, only for eligible PRs, and
        # only after the merge is observed: website.yml deploys main, so an
        # early dispatch would deploy the pre-merge commit.
        dispatch = re.search(
            r"(?ms)^      - name: Dispatch Website publish once merged\n"
            r"        if: steps\.guard\.outputs\.eligible == 'true'\n"
            r"(.*?)(?=^      - name: |\Z)",
            automerge,
        )
        self.assertIsNotNone(dispatch, "automerge workflow has no guarded dispatch step")
        step = dispatch.group(1)
        self.assertIn("--json state,autoMergeRequest", step)
        # `gh pr view --jq` takes a single expression, so `--jq -r '<prog>'`
        # passes `-r` as the expression and `<prog>` as a second positional,
        # which gh rejects (`accepts at most 1 arg(s), received 2`) before
        # any API call; the poll then loops on FETCH_FAILED until the
        # deadline instead of dispatching. Parse the poll's argv so a
        # substring check alone cannot pass that bug.
        self.assertNotRegex(step, r"--jq\s+-r\b")
        poll = re.search(
            r"gh pr view\s+(.*?)\|\|\s*echo FETCH_FAILED", step, re.DOTALL
        )
        self.assertIsNotNone(poll, "dispatch step has no parseable gh pr view poll")
        argv = shlex.split(poll.group(1).replace("\\\n", " "))
        self.assertIn("--jq", argv)
        self.assertNotIn("-r", argv)
        self.assertEqual(argv.count("--jq"), 1)
        jq_index = argv.index("--jq")
        self.assertEqual(
            len(argv),
            jq_index + 2,
            "gh pr view takes one --jq expression and no extra positional",
        )
        program = argv[jq_index + 1]
        self.assertIn("\\(.state)", program)
        self.assertIn("\\(.autoMergeRequest != null)", program)
        self.assertEqual(
            argv[:jq_index],
            ["$PR_NUMBER", "--repo", "$REPO", "--json", "state,autoMergeRequest"],
        )
        self.assertIn("MERGED", step)
        self.assertRegex(step, r"gh workflow run website\.yml --repo .+ --ref main")
        self.assertLess(
            automerge.index("MERGED"),
            automerge.index("gh workflow run website.yml"),
            "the dispatch must wait for the merge instead of firing at arm time",
        )

        # The dispatch must land: website.yml offers workflow_dispatch and its
        # publish job runs for non-pull_request events on main.
        self.assertIn("workflow_dispatch:", website)

        # The Cloudflare deploy token stays out of the automerge job: no
        # secrets and no environment there; secrets live only in website.yml.
        self.assertNotIn("secrets.", automerge)
        self.assertNotRegex(automerge, r"(?m)^    environment:")
        self.assertIn("secrets.CLOUDFLARE_API_TOKEN", website)

    def test_live_snapshot_boards(self):
        directory = build.latest_analytics_dir()
        self.assertIsNotNone(directory)
        data = json.loads((directory / "scorecards.json").read_text(encoding="utf-8"))
        doc = build.render_ranking_page(data, directory.name, build.load_rank(directory), weekly=())
        self.assertIn(f'Snapshot <time datetime="{directory.name}">{directory.name}</time> · last 30 days', doc)
        self.assertIn('href="/notes/crew-rankings-method/"', doc)
        boards = [
            ("implementer-crews", data["implementers"]),
            ("reviewers-provisional", data["reviewers"]["provisional"]),
            ("pilot-crews", data["pilots"]),
            ("tiers", data["implementers_by_tier"]),
        ]
        if data["reviewers"].get("settled"):
            boards.append(("reviewers-settled", data["reviewers"]["settled"]))
        for element_id, payload in boards:
            block = section(doc, element_id)
            since, until = payload["window"]["since"], payload["window"]["until"]
            self.assertIn(f'datetime="{since}"', block)
            self.assertIn(f'datetime="{until}"', block)
            self.assertIn("UTC.", block)
            self.assertIn("per 100 ", block.lower())
        # The old per-tier board anchors still land on the page.
        for tier in build.TIER_ORDER:
            self.assertIn(f'id="implementers-{tier}"', doc)
        self.assertIn(">Provisional<", doc)
        self.assertIn(">unranked<", doc)
        self.assertNotIn("orchestrator-only", doc)
        self.assertIn("Orchestrators are not scored on this page.", doc)
        for gap in ("model unknown", "crew unknown", "crew unavailable", "system"):
            self.assertNotIn(gap, doc)
        for needle in ("ORB-", "jrun-", "/home/", "ws_"):
            self.assertNotIn(needle, doc)
        self.assertNotIn("dropped", doc)
        # Progressive enhancement: tabs and toggle come from analytics.js.
        self.assertIn("/assets/analytics.js?v=", doc)
        self.assertIn("/assets/analytics.css?v=", doc)
        self.assertIn('<nav class="group-nav" aria-label="Ranking views">', doc)
        self.assertIn('class="board-toggle" role="group" aria-label="Review window" hidden', doc)

    def test_live_snapshot_heatmap_keeps_models_apart(self):
        # luna on gpt-6-luna and luna on gpt-6.1-luna are separate rows, as on
        # the overall board: summing every luna cell would read 654 low tasks.
        directory = build.latest_analytics_dir()
        data = json.loads((directory / "scorecards.json").read_text(encoding="utf-8"))
        # A slot is one crew, model and effort; a snapshot that splits rows by
        # effort has one slot per effort, each summing only its own cells.
        slots, _min_support = build.tier_slots(data["implementers_by_tier"])
        low = slots["low"]
        for (crew, model, effort), slot in low.items():
            if crew != "luna":
                continue
            expected = sum(
                cell["n"] for cell in data["implementers_by_tier"]["cells"]
                if cell["tier"] == "low" and cell["crew"] == crew and cell["model"] == model
                and build.effort_text(cell) == effort
            )
            self.assertEqual(slot["units"], expected)
        self.assertTrue(any(key[:2] == ("luna", "gpt-6-luna") for key in low))
        self.assertTrue(any(key[:2] == ("luna", "gpt-6.1-luna") for key in low))
        main = max((slot for key, slot in low.items() if key[:2] == ("luna", "gpt-6-luna")), key=lambda slot: slot["units"])
        doc = build.render_ranking_body(data, directory.name)
        tiers = section(doc, "tiers")
        self.assertIn(f'{main["units"]:,} tasks', tiers)
        self.assertNotIn(f'{main["units"] + 1:,} tasks', tiers)

    def test_takeaways_are_derived_from_the_tiers(self):
        directory = build.latest_analytics_dir()
        data = json.loads((directory / "scorecards.json").read_text(encoding="utf-8"))
        doc = build.render_ranking_body(data, directory.name)
        cards = re.search(r'<ul class="tiles takeaways".*?</ul>', doc).group(0)
        slots, _ = build.tier_slots(data["implementers_by_tier"])
        for tier in build.TIER_ORDER:
            leaders = [slot for slot in slots[tier].values() if slot["rank"] == 1]
            if leaders:
                self.assertIn(leaders[0]["crew"], cards)
        text = re.sub(r"<[^>]+>", "", cards)
        sized = [slot for tier in build.TIER_ORDER for slot in slots[tier].values() if slot["rank"] is not None]
        weakest = min(sized, key=lambda slot: slot["score"])
        self.assertIn(f'{build.crew_label(weakest)} {build.fmt_score(weakest["score"])}', text)
        self.assertIn(">Watch<", cards)

    def test_term_breakdown_flags_best_worst_and_unmeasured(self):
        data = scorecards()
        data["implementers"]["terms"] = [
            {"group": "credit", "key": "landed", "label": "Landed", "weight": 1.0},
            {"group": "problem", "key": "rework", "label": "Rework", "weight": -1.0},
        ]
        data["implementers"]["fleet_average"] = 120
        data["implementers"]["rows"] = [
            dict(row("haiku", "claude-haiku-5-5", 30, 1, 146.38), per_100={"landed": 98.0, "rework": 2.0}),
            dict(row("opus", "claude-opus-5-5", 40, 2, 100.0), per_100={"landed": 90.0, "rework": None}),
            dict(row("sol", "gpt-sol", 50, 3, 90.0), per_100={"landed": 80.0, "rework": 9.0}),
            dict(row("tiny", "gpt-tiny", 2, None, 300.0), per_100={"landed": 100.0, "rework": 0.0}),
        ]
        doc = build.render_ranking_body(data, "2026-11-08")
        overall = section(doc, "implementer-crews")

        def crew(name):
            start = overall.index(f'<span class="crew-name">{name}</span>')
            return overall[start:overall.index("</details>", start)]

        haiku, opus, sol = crew("haiku"), crew("opus"), crew("sol")
        self.assertRegex(haiku, r'term is-better" data-term="landed".*best of ranked crews')
        self.assertRegex(haiku, r'term is-better" data-term="rework"')
        self.assertRegex(sol, r'term is-worse" data-term="landed".*worst of ranked crews')
        self.assertRegex(sol, r'term is-worse" data-term="rework"')
        self.assertIn("not measured for this crew", opus)
        # Bars are coloured against the fleet average, with its marker.
        self.assertIn('score-fill is-better', haiku)
        self.assertIn('score-fill is-worse', opus)
        self.assertIn('class="fleet-mark" style="left:', haiku)
        # The below-support crew is folded, not ranked or used for best/worst.
        folded = overall[overall.index('<details class="more unranked-crews">'):]
        self.assertIn("1 crew under 10 implemented tasks, not ranked", folded)
        self.assertIn(">tiny<", folded)
        self.assertNotIn('class="crew-name">tiny<', overall)

    def test_filters_gaps_unranked_rows_and_orchestrators(self):
        doc = build.render_ranking_body(scorecards(), "2026-11-08")
        implementers = section(doc, "implementer-crews")
        self.assertIn("haiku", implementers)
        self.assertIn("per 100 implemented tasks", implementers)
        self.assertIn('data-rank="1"', implementers)
        self.assertIn("tiny", implementers)
        self.assertIn('data-rank="unranked"', implementers)
        for gap in ("crew unavailable", "model unknown", "crew unknown", "orchestrator-only", "secret-model"):
            self.assertNotIn(gap, doc)
        self.assertIn("1,387 reviews in this window are still provisional.", doc)
        self.assertIn(">Provisional<", section(doc, "reviewers-provisional"))
        settled = section(doc, "reviewers-settled")
        self.assertIn(">Settled<", settled)
        self.assertIn("2026-09-09T09:11:48Z", settled)
        self.assertIn("per 100 settled reviews", settled)
        self.assertIn("per 100 assessed tasks", section(doc, "pilot-crews"))

    def test_tier_heatmap_sums_types_and_reranks(self):
        doc = build.render_ranking_body(scorecards(), "2026-11-08")
        tiers = section(doc, "tiers")
        self.assertIn('datetime="2026-10-09T09:11:25Z"', tiers)
        self.assertIn("Each tier's fleet rate is 100", tiers)
        self.assertIn('id="implementers-low"', tiers)
        slots, min_support = build.tier_slots(scorecards()["implementers_by_tier"])
        self.assertEqual(min_support, 10)
        low = slots["low"]
        # A snapshot without efforts keys each slot with no effort.
        self.assertEqual(low[("haiku", "claude-haiku-5-5", None)]["units"], 12)
        self.assertEqual(low[("haiku", "claude-haiku-5-5", None)]["rank"], 2)
        self.assertEqual(low[("opus", "claude-opus-5-5", None)]["rank"], 1)
        self.assertIsNone(low[("thin", "gpt-thin", None)]["rank"])
        self.assertNotIn(("gap", "model unknown", None), low)

        def cell(name):
            start = tiers.index(f'<span class="crew-name">{name}</span>')
            return tiers[start:tiers.index("</tr>", start)]

        self.assertIn('data-rank="1"', cell("opus"))
        self.assertIn("★", cell("opus"))
        self.assertIn("12 tasks", cell("haiku"))
        self.assertNotIn("★", cell("haiku"))
        # A crew with only small samples and no overall rank folds away, faded.
        folded = tiers[tiers.index("<details"):]
        self.assertIn("1 more crew with only small tier samples", folded)
        self.assertIn("is-thin", cell("thin"))
        self.assertIn("3 tasks · unranked", cell("thin"))
        self.assertNotIn(">gap<", tiers)
        self.assertEqual(build.heat_class(130), "hm-b2")
        self.assertEqual(build.heat_class(110), "hm-b1")
        self.assertEqual(build.heat_class(100), "hm-0")
        self.assertEqual(build.heat_class(80), "hm-w1")
        self.assertEqual(build.heat_class(60), "hm-w2")

    def test_tier_heatmap_card_cells_and_small_print_below(self):
        block = {
            "cells": [
                {"crew": "best", "crew_mean": 140.0, "model": "m-best", "n": 20, "tier": "low", "type": "ui"},
                {"crew": "mid", "crew_mean": 90.0, "model": "m-mid", "n": 12, "tier": "medium", "type": "ui"},
                {"crew": "thin", "crew_mean": 180.0, "model": "m-thin", "n": 3, "tier": "low", "type": "ui"},
            ],
            "min_support": 7,
            "unit": "tasks",
            "window": window("2026-10-09T09:11:25Z", "2026-11-08T09:11:25Z"),
        }
        heatmap, _slots = build.tier_heatmap(block, [])
        # One legend line under the heading, threshold from the data.
        self.assertIn(
            "Each tier's fleet rate is 100. ★ marks the best ranked crew in a tier; "
            "faded cells have under 7 tasks and stay unranked.", heatmap)
        self.assertLess(heatmap.index("faded cells have under 7 tasks"), heatmap.index("<table"))
        # Starred ranked cell: star, score and task count, no unranked mark.
        best = heatmap[heatmap.index('<span class="crew-name">best</span>'):]
        best = best[:best.index("</tr>")]
        self.assertIn('data-rank="1"', best)
        self.assertIn("★", best)
        self.assertIn("20 tasks", best)
        self.assertNotIn("unranked", best)
        # Faded cell: greyed (is-thin), score shown, counted as unranked.
        self.assertIn('data-rank="unranked"', heatmap)
        self.assertIn("is-thin", heatmap)
        self.assertIn("3 tasks · unranked", heatmap)
        # Empty cell: a bordered card with a visible dash and "no tasks".
        self.assertIn('class="hm hm-none"', heatmap)
        self.assertIn('<span class="hm-score">–</span><span class="hm-sub">no tasks</span>', heatmap)
        self.assertNotIn('<span class="sr-only">no tasks</span>', heatmap)
        # Window and score definition sit below the table as small print.
        foot = heatmap[heatmap.index('<div class="hm-foot">'):]
        self.assertGreater(heatmap.index('<div class="hm-foot">'), heatmap.index("</table>"))
        self.assertIn('datetime="2026-10-09T09:11:25Z"', foot)
        self.assertIn(build.TIER_SCORE_KEY.replace("'", "&#x27;"), foot)
        self.assertNotIn('datetime="2026-10-09T09:11:25Z"', heatmap[:heatmap.index('<div class="hm-foot">')].split("<table", 1)[0])

    def test_settled_board_hidden_when_absent(self):
        data = scorecards()
        data["reviewers"]["settled"] = None
        doc = build.render_ranking_body(data, "2026-11-08")
        self.assertNotIn("reviewers-settled", doc)
        self.assertNotIn(">Settled<", doc)
        self.assertNotIn("2026-09-09T09:11:48Z", doc)
        self.assertIn(">Provisional<", doc)

    def test_refuses_a_window_other_than_30d(self):
        data = scorecards()
        data["pilots"]["window"]["key"] = "7d"
        with self.assertRaises(SystemExit):
            build.render_ranking_body(data, "2026-11-08")

    def test_newest_snapshot_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            older = root / "data" / "analytics" / "2026-01-01"
            newer = root / "data" / "analytics" / "2026-11-08"
            older.mkdir(parents=True)
            newer.mkdir(parents=True)
            (older / "scorecards.json").write_text("{}", encoding="utf-8")
            (newer / "scorecards.json").write_text("{}", encoding="utf-8")
            self.assertEqual(build.latest_analytics_dir(root), newer)
            broken = root / "data" / "analytics" / "2026-12-01"
            broken.mkdir()
            with self.assertRaises(SystemExit):
                build.latest_analytics_dir(root)

    def test_analytics_index_projects_only_validated_snapshot_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "2026-11-08"
            directory.mkdir()
            meta = {"windows": {"reliability": {"label": "30d", "since": "2026-10-09T00:00:00Z", "until": "2026-11-08T00:00:00Z"}}, "secret": "ORB-12345 /private/path host.internal"}
            (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
            document = build.render_analytics_index(directory)
            for slug in ("metrics", "reliability", "experiments"):
                self.assertIn(f'href="/analytics/{slug}/"', document)
            # The agents card is now the Ranking card.
            self.assertIn('href="/ranking/"', document)
            self.assertNotIn('href="/analytics/agents/"', document)
            for expected in ("2026-11-08", "2026-10-09T00:00:00Z", "/notes/crew-rankings-method/"):
                self.assertIn(expected, document)
            for secret in ("ORB-12345", "/private/path", "host.internal"):
                self.assertNotIn(secret, document)
            meta["windows"]["reliability"]["since"] = "ORB-12345"
            (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
            with self.assertRaises(SystemExit):
                build.render_analytics_index(directory)

    def test_notes_header_stays_current_only_on_notes(self):
        self.assertEqual(build.header_html("notes"), build.HEADER)
        self.assertIn('href="/analytics/" aria-current="page"', build.header_html("analytics"))
        self.assertNotIn('href="/notes/" aria-current="page"', build.header_html("analytics"))
        ranking = build.header_html("ranking")
        self.assertIn('href="/ranking/" aria-current="page"', ranking)
        self.assertEqual(ranking.count('aria-current="page"'), 1)

    def test_nav_reads_notes_ranking_analytics_orbit_github(self):
        index = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        for source in (build.HEADER, build.analytics_page.HEADER, index):
            nav = re.search(r"<nav>(.*?)</nav>", source, re.S).group(1)
            labels = re.findall(r"<a [^>]*>([^<]+)</a>", nav)
            self.assertEqual(labels, ["Notes", "Ranking", "Analytics", "Orbit", "GitHub"])

    def test_ranking_page_has_four_tabs_and_one_method_section(self):
        doc = build.render_ranking_page(scorecards(), "2026-11-08", rank_board(), weekly=())
        self.assertIn('href="/ranking/" aria-current="page"', doc)
        tabs = re.findall(r'data-tab="([a-z]+)"', doc)
        self.assertEqual(tabs, ["overall", "implementers", "reviewers", "pilots"])
        groups = re.findall(r'<div class="role-group" data-group="([a-z]+)" id="\1"', doc)
        self.assertEqual(groups, tabs)
        # Each tab opens with four stat cards.
        for key in tabs:
            start = doc.index(f'data-group="{key}"')
            panel = doc[start:doc.find('class="role-group"', start + 1) if key != "pilots" else doc.index('id="method"')]
            cards = re.search(r'<ul class="stat-cards".*?</ul>', panel, re.S)
            self.assertIsNotNone(cards, key)
            self.assertEqual(cards.group(0).count('<li class="stat">'), 4, key)
        # Newest snapshot only: no picker, no window chips, no archive links.
        self.assertNotIn("snapshot-picker", doc)
        self.assertNotIn("/analytics/agents/", doc)
        self.assertNotRegex(doc, r'href="/ranking/\d{4}-\d{2}/"')
        # Method and windows sits outside the tab panels, so every tab shows it.
        self.assertEqual(doc.count('id="method"'), 1)
        method = doc[doc.index('id="method"'):]
        self.assertIn('href="/notes/crew-rankings-method/"', method)
        self.assertIn("Weekly write-ups", method)
        self.assertIn("data/analytics/2026-11-08", method)

    def test_all_roles_index_rescales_weights_over_held_roles_with_a_two_role_minimum(self):
        rule = build.OVERALL_RULE
        self.assertEqual(rule["weights"], (("implementers", 60), ("reviewers", 25), ("pilots", 15)))
        self.assertEqual(rule["min_roles"], 2)
        self.assertNotIn("missing_role_index", rule)
        data = all_roles_scorecards()
        overall = build.overall_models(data)
        rows = {row["model"]: row for row in overall["rows"]}
        # Ranked in at least two roles; one-role models are listed, not ranked.
        self.assertEqual(set(rows), {"model-ir", "model-ip", "model-rp", "model-all"})
        self.assertEqual(overall["one_role"], [("model-i", "implementers"), ("model-r", "reviewers")])
        # implementer + reviewer: 60/85 and 25/85, nothing imputed for the pilot role.
        self.assertAlmostEqual(rows["model-ir"]["overall"], (60 * 120 + 25 * 80) / 85)
        self.assertIsNone(rows["model-ir"]["cells"]["pilots"])
        self.assertEqual(rows["model-ir"]["roles"], ["implementers", "reviewers"])
        # implementer + pilot: 60/75 and 15/75.
        self.assertAlmostEqual(rows["model-ip"]["overall"], (60 * 90 + 15 * 150) / 75)
        # reviewer + pilot: 25/40 and 15/40.
        self.assertAlmostEqual(rows["model-rp"]["overall"], (25 * 110 + 15 * 50) / 40)
        # All three roles: the plain 60/25/15 mean.
        self.assertAlmostEqual(rows["model-all"]["overall"], (60 * 100 + 25 * 100 + 15 * 100) / 100)
        # The old rule would have imputed 100 for model-ir's pilot role.
        self.assertNotAlmostEqual(rows["model-ir"]["overall"], (60 * 120 + 25 * 80 + 15 * 100) / 100)
        self.assertEqual([row["model"] for row in overall["rows"]], ["model-ir", "model-ip", "model-all", "model-rp"])
        # Changing the constant changes the result and the stated rule.
        three = {"weights": rule["weights"], "min_roles": 3}
        self.assertEqual([row["model"] for row in build.overall_models(data, three)["rows"]], ["model-all"])
        text = build.overall_rule_text()
        self.assertIn("60% implementer + 25% reviewer + 15% pilot", text)
        self.assertIn("at least two roles", text)
        self.assertIn("rescaled", text)
        self.assertNotIn("counts as 100", text)
        doc = build.render_ranking_body(data, "2026-11-08", rank_board())
        board_html = doc[doc.index('id="all-roles"'):]
        board_html = board_html[:board_html.index("</section>")]
        self.assertIn("All-roles index", board_html)
        self.assertIn("Unlike Model rank", board_html)
        self.assertIn("In one role only, not ranked: model-i (implementer) and model-r (reviewer).", plain(board_html))
        self.assertNotIn('class="crew-name">' + build.model_dot("model-i") + "model-i<", board_html)
        method = doc[doc.index('id="method"'):]
        self.assertIn("<h3>All-roles index</h3>", method)
        self.assertIn("at least two roles", method)

    def test_overall_pools_crews_into_their_model_by_units(self):
        data = scorecards()
        data["implementers"]["rows"] = [
            row("haiku", "claude-haiku-5-5", 30, 1, 150.0),
            row("haiku@high", "claude-haiku-5-5", 10, 2, 110.0),
            row("opus", "claude-opus-5-5", 20, 3, 100.0),
        ]
        data["implementers"]["fleet_average"] = 125.0
        data["reviewers"]["provisional"]["fleet_average"] = 200.0
        data["pilots"]["fleet_average"] = 40.0
        overall = build.overall_models(data)
        cells = {row["model"]: row["cells"]["implementers"] for row in overall["rows"]}
        self.assertAlmostEqual(cells["claude-haiku-5-5"]["score"], (150 * 30 + 110 * 10) / 40)
        self.assertEqual(cells["claude-haiku-5-5"]["units"], 40)
        self.assertAlmostEqual(cells["claude-haiku-5-5"]["index"], (150 * 30 + 110 * 10) / 40 / 125 * 100)
        self.assertEqual(cells["claude-opus-5-5"]["place"], 2)

    def test_rows_split_by_effort_name_the_effort_beside_the_crew(self):
        doc = build.render_ranking_body(effort_scorecards(), "2026-11-09")
        sol_est, sol_high = ("sol · effort unknown", "gpt-6.1-sol"), ("sol@high", "gpt-6.1-sol")
        opus = ("opus@medium", "claude-opus-5-5")
        boards = {
            "implementer-crews": [sol_est, sol_high, opus, ("haiku@high", "claude-haiku-5-5"),
                                  ("argon · effort unknown", "gemini-4-argon-high")],
            "tiers": [sol_est, sol_high, opus],
            "reviewers-provisional": [sol_est, sol_high, opus],
            "reviewers-settled": [sol_est, sol_high],
            "pilot-crews": [sol_high, sol_est, opus],
        }
        for element_id, expected in boards.items():
            with self.subTest(board=element_id):
                board_html = section(doc, element_id)
                crews = board_crews(board_html)
                self.assertEqual(crews, expected)
                self.assertEqual(len(set(crews)), len(crews), "two rows on one board read the same")
                # No board carries an estimate note: nothing is guessed.
                self.assertNotIn("est-note", board_html)
                self.assertNotIn("(est.)", board_html)
        # The effort sits in the secondary style inside the crew name, on its line;
        # a crew already named with its effort is split the same way.
        self.assertIn('<span class="crew-name">sol<span class="crew-effort">@high</span></span>', doc)
        self.assertIn('<span class="crew-name">sol<span class="crew-effort"> · effort unknown</span></span>', doc)
        self.assertIn('<span class="crew-name">haiku<span class="crew-effort">@high</span></span>', doc)
        # The unranked fold names the effort too.
        folded = section(doc, "implementer-crews")
        folded = plain(folded[folded.index('<details class="more unranked-crews"'):])
        self.assertIn("sol@xhigh", folded)
        # Each effort keeps its own tier slot: sums are not merged across efforts.
        tiers = section(doc, "tiers")
        self.assertIn("12 tasks", tiers)
        self.assertNotIn("22 tasks", tiers)
        slots, _ = build.tier_slots(effort_scorecards()["implementers_by_tier"])
        self.assertEqual(slots["low"][("sol", "gpt-6.1-sol", "high")]["units"], 12)
        self.assertEqual(slots["low"][("sol", "gpt-6.1-sol", "effort unknown")]["units"], 10)

    def test_crew_label_rule(self):
        def label(crew, **fields):
            return build.crew_label({"crew": crew, **build.crew_view({"crew": crew, **fields})})

        self.assertEqual(label("sol"), "sol")  # snapshot without efforts
        self.assertEqual(label("haiku@high"), "haiku@high")
        self.assertEqual(label("sol", reasoning_effort="high", effort_label="high"), "sol@high")
        self.assertEqual(label("haiku@high", reasoning_effort="high", effort_label="high"), "haiku@high")
        # An effort_estimate from an older snapshot is ignored: the effort is unknown.
        self.assertEqual(label("sol", reasoning_effort="unknown", effort_label="effort unknown",
                               effort_estimate="high"), "sol · effort unknown")
        self.assertEqual(label("argon", reasoning_effort="unknown", effort_label="effort unknown"),
                         "argon · effort unknown")
        self.assertEqual(label("argon", effort_label="provider default"), "argon · provider default")

    def test_callouts_name_the_effort_beside_the_crew(self):
        doc = build.render_ranking_body(effort_scorecards(), "2026-11-09")
        callouts = re.findall(r'<ul class="tiles takeaways" aria-label="(?:Takeaways|Callouts)">.*?</ul>', doc)
        self.assertEqual(len(callouts), 3)
        implementers, reviewers, pilots = (plain(item) for item in callouts)
        self.assertIn("sol · effort unknown 130.0, sol@high 120.0", implementers)
        self.assertIn("sol@high 125.0, sol · effort unknown 105.0", implementers)
        # Different efforts lead the two tiers, so they are not merged into one card.
        self.assertNotIn("leads both tiers", implementers)
        self.assertIn("opus@medium 80.0 on low", implementers)
        self.assertIn("Topsol · effort unknown 130.0", reviewers)
        self.assertIn("Below fleetopus@medium 80.0, sol@high 90.0", reviewers)
        self.assertIn("Topsol@high 60.0", pilots)
        self.assertIn("sol · effort unknown 40.0", pilots)
        self.assertIn('<span class="takeaway-head">sol<span class="crew-effort">@high</span> 60.0</span>', doc)
        # The top-crew stat card names the effort as well.
        self.assertIn('<span class="stat-value">sol · effort unknown</span>', doc)
        self.assertNotIn("(est.)", doc)

    def test_overall_pools_every_effort_row_into_its_model(self):
        data = effort_scorecards()
        overall = build.overall_models(data)
        cells = {row["model"]: row["cells"] for row in overall["rows"]}
        sol = cells["gpt-6.1-sol"]
        self.assertEqual(sol["implementers"]["units"], 50)
        self.assertAlmostEqual(sol["implementers"]["score"], (132.6 * 30 + 115.5 * 20) / 50)
        self.assertEqual(sol["reviewers"]["units"], 27)
        self.assertAlmostEqual(sol["reviewers"]["score"], (130.0 * 15 + 90.0 * 12) / 27)
        self.assertEqual(sol["pilots"]["units"], 23)
        self.assertEqual([row["model"] for row in overall["rows"]].count("gpt-6.1-sol"), 1)
        row_ = next(row for row in overall["rows"] if row["model"] == "gpt-6.1-sol")
        self.assertEqual(row_["crews"], ["sol · effort unknown", "sol@high"])
        doc = build.render_ranking_body(data, "2026-11-09")
        self.assertIn('<span class="crew-model">sol: high, effort unknown</span>', doc)
        overall_html = doc[doc.index('aria-labelledby="all-roles-title"'):]
        overall_html = overall_html[:overall_html.index("</section>")]
        self.assertNotIn("est-note", overall_html)

    def test_rank_rows_order_a_shared_band_by_score(self):
        rows = [rank_row("cheap", 2, "2=", 64.1, 40, ["c"]), rank_row("top", 1, "1", 115.8, 40, ["t"]),
                rank_row("luna", 2, "2=", 107.0, 40, ["l"]), rank_row("sol", 2, "2=", 108.0, 40, ["s"]),
                rank_row("tie-b", 2, "2=", 90.5, 40, ["b"]), rank_row("tie-a", 2, "2=", 90.5, 40, ["a"])]
        ranked, _rest = build.rank_rows({"rows": rows})
        self.assertEqual([row["model"] for row in ranked], ["top", "sol", "luna", "tie-a", "tie-b", "cheap"])

    def test_crews_are_grouped_by_crew_with_their_efforts(self):
        group = build.analytics_page.crew_groups_text
        self.assertEqual(group(["haiku@xhigh", "haiku · effort unknown", "haiku@high"]),
                         "haiku: xhigh, high, effort unknown")
        self.assertEqual(group(["opus · effort unknown", "sol · effort unknown"]),
                         "opus: effort unknown · sol: effort unknown")
        self.assertEqual(group(["sol@high", "luna · effort unknown", "sol@xhigh", "sol@high"]),
                         "sol: high, xhigh · luna: effort unknown")
        self.assertEqual(group(["haiku", "opus"]), "haiku · opus")
        self.assertEqual(group([]), "")

    def test_snapshot_without_efforts_renders_crews_as_before(self):
        doc = build.render_ranking_body(scorecards(), "2026-11-08")
        self.assertNotIn("crew-effort", doc)
        self.assertNotIn("effort unknown", doc)
        self.assertNotIn("est-note", doc)
        self.assertIn('<span class="crew-name">haiku</span><span class="crew-model">claude-haiku-5-5</span>', doc)
        data = scorecards()
        data["implementers"]["rows"] = [
            row("haiku", "claude-haiku-5-5", 30, 1, 150.0),
            row("haiku@high", "claude-haiku-5-5", 10, 2, 110.0),
        ]
        data["implementers"]["fleet_average"] = 125.0
        data["pilots"]["fleet_average"] = 40.0
        overall = build.overall_models(data)
        haiku = next(item for item in overall["rows"] if item["model"] == "claude-haiku-5-5")
        self.assertEqual(haiku["crews"][:2], ["haiku", "haiku@high"])
        self.assertIn('<span class="crew-model">haiku: high</span>', build.render_ranking_body(data, "2026-11-08"))

    def test_overall_shows_model_rank_then_all_roles_index(self):
        data = all_roles_scorecards()
        doc = build.render_ranking_body(data, "2026-11-08", rank_board())
        overall = doc[doc.index('data-group="overall"'):doc.index('data-group="implementers"')]
        # In order: Model rank, then the All-roles index.
        self.assertLess(overall.index('<h2 id="models-title">Model rank</h2>'),
                        overall.index('<h2 id="all-roles-title">All-roles index</h2>'))
        models = overall[overall.index('id="models"'):overall.index('id="all-roles"')]
        # Eligible models only, in Rank's order, with band labels, interval, cost ratio and breakdown.
        self.assertEqual(re.findall(r'<span class="ml-name">([^<]+)</span>', models),
                         ["claude-haiku-5-5", "claude-opus-5-5", "gpt-6-luna"])
        for needle in ("p10", "0.75×", "$1.50", "97.0%", '<details class="model-row">', "Score contributions"):
            self.assertIn(needle, models)
        # One live/provisional line, and the live window.
        self.assertEqual(models.count("This is Orbit&#x27;s live model rank: provisional, because late escaped "
                                      "regressions may still arrive."), 1)
        self.assertIn("Live window", models)
        self.assertIn('datetime="2026-10-09T06:00:00Z"', models)
        self.assertNotIn("Settled window", models)
        # Not ranked yet: the rule and the reasons are rank.json's own text.
        folded = models[models.index('<details class="more not-ranked">'):]
        self.assertIn("Orbit fixture rule: 30 tasks in one tier of 5+.", folded)
        self.assertIn("Orbit says: 9 of 30 tasks so far", folded)
        self.assertNotIn("across 2 tiers", folded)
        self.assertNotIn("model unknown", doc)
        # The Implementers tab no longer shows the Models board.
        implementers = doc[doc.index('data-group="implementers"'):doc.index('data-group="reviewers"')]
        self.assertNotIn('class="model-board"', implementers)
        self.assertNotIn("models-title", implementers)
        self.assertIn('id="crews-implementers"', implementers)
        self.assertEqual(doc.count('id="models"'), 1)

    def test_podium_follows_model_rank(self):
        data = all_roles_scorecards()
        doc = build.render_ranking_body(data, "2026-11-08", rank_board())
        podium = re.search(r'<ol class="podium" aria-label="Top three models by Model rank">.*?</ol>', doc, re.S)
        self.assertIsNotNone(podium)
        cards = re.findall(r'<span class="podium-place">([^<]+)</span>.*?<span>([^<]+)</span></span>.*?'
                           r'<span class="podium-value">([^<]+)</span>', podium.group(0), re.S)
        self.assertEqual(cards, [("1st", "claude-haiku-5-5", "120.0"), ("2nd", "claude-opus-5-5", "104.0"),
                                 ("3rd", "gpt-6-luna", "90.0")])
        # The leader card agrees with Model rank.
        self.assertIn('<span class="stat-value">claude-haiku-5-5</span>', doc)
        # A shared band keeps Rank's order and marks the tie.
        tied = rank_board()
        tied["rows"][1]["rank"], tied["rows"][1]["rank_label"] = 2, "2="
        tied["rows"][2]["rank"], tied["rows"][2]["rank_label"] = 2, "2="
        places = [item["place"] for item in build.podium_from_rank(tied)]
        self.assertEqual(places, ["1st", "2nd=", "2nd="])

    def settled_board(self, **overrides):
        board = rank_board()
        board["live"] = board["provisional"] = False
        board["settle_lag"] = "14d"
        board["scales_source"] = "season"
        board["qualified"] = True
        board.update(overrides)
        return board

    def assert_no_model_rank_places(self, doc, reason):
        overall = doc[doc.index('data-group="overall"'):doc.index('data-group="implementers"')]
        models = overall[overall.index('id="models"'):overall.index('id="all-roles"')]
        self.assertNotIn('class="podium"', overall)
        self.assertNotIn("podium-place", overall)
        self.assertNotIn("data-rank=", models)
        self.assertNotRegex(models, r'class="ml-rank">[^<]*\d')
        self.assertNotIn(">Rank</span>", models)
        self.assertNotIn("Top three models by Model rank", overall)
        self.assertIn("not published", overall)
        self.assertIn("no ranks on this board", overall)
        self.assertIn(reason, models)
        self.assertIn("120.0", models)
        self.assertIn("p10", models)
        self.assertIn("Settled window", models)

    def test_window_estimate_renders_scores_without_ranks_or_a_podium(self):
        board = self.settled_board(scales_source="window_estimate", qualified=True)
        doc = build.render_ranking_body(all_roles_scorecards(), "2026-11-08", board)
        self.assert_no_model_rank_places(
            doc,
            "No ranking is published: the noise scales are estimated from this window, "
            "not frozen for a calibrated season, so scores and intervals are shown without ranks or a podium.",
        )
        self.assertNotIn("the board has not qualified", doc[doc.index('id="models"'):doc.index('id="all-roles"')])

    def test_unqualified_board_renders_scores_without_ranks_or_a_podium(self):
        board = self.settled_board(scales_source="season", qualified=False)
        # Orbit awards no bands on an unqualified board; the scores stay.
        for row in board["rows"]:
            if row["eligible"]:
                row["rank"] = None
                row["rank_label"] = None
        doc = build.render_ranking_body(all_roles_scorecards(), "2026-11-08", board)
        self.assert_no_model_rank_places(
            doc,
            "No ranking is published: the board has not qualified, "
            "so scores and intervals are shown without ranks or a podium.",
        )

    def test_window_estimate_and_unqualified_names_both_reasons(self):
        board = self.settled_board(scales_source="window_estimate", qualified=False)
        doc = build.render_ranking_body(scorecards(), "2026-11-08", board)
        self.assertIn(
            "the noise scales are estimated from this window, not frozen for a calibrated season, "
            "and the board has not qualified",
            doc,
        )
        self.assertNotIn('class="podium"', doc)

    def test_calibrated_qualified_settled_board_renders_podium_and_bands(self):
        board = self.settled_board()
        doc = build.render_ranking_body(all_roles_scorecards(), "2026-11-08", board)
        overall = doc[doc.index('data-group="overall"'):doc.index('data-group="implementers"')]
        podium = re.search(r'<ol class="podium" aria-label="Top three models by Model rank">.*?</ol>', overall, re.S)
        self.assertIsNotNone(podium)
        self.assertIn('class="ml-rank">1', overall)
        self.assertIn('class="band-start"', overall)
        self.assertIn("Settled window", overall)
        self.assertIn("two to six weeks old", overall)
        self.assertNotIn("live model rank", overall)
        self.assertNotIn("No ranking is published", overall)
        self.assertIn('<span class="stat-value">claude-haiku-5-5</span>', overall)

    def test_live_snapshot_keeps_its_places_and_is_labelled_provisional(self):
        # The stored 2026-11-09 board is live and a window estimate. It still
        # renders as published, labelled provisional, rather than being rewritten.
        board = rank_board()
        board["scales_source"] = "window_estimate"
        board["qualified"] = True
        board["settle_lag"] = "14d"
        doc = build.render_ranking_body(all_roles_scorecards(), "2026-11-09", board)
        overall = doc[doc.index('data-group="overall"'):doc.index('data-group="implementers"')]
        self.assertIn("This is Orbit&#x27;s live model rank: provisional, because late escaped regressions "
                      "may still arrive.", overall)
        self.assertIn("Live window", overall)
        self.assertIn('class="podium"', overall)
        self.assertIn('class="ml-rank">1', overall)
        self.assertNotIn("No ranking is published", overall)

    def test_model_rank_crew_lists_label_bare_crews_and_hide_system(self):
        board = rank_board()
        board["rows"][0]["crews"] = [
            {"crew": "haiku", "tasks": 590, "effort_estimate": "xhigh"},
            {"crew": "haiku@xhigh", "tasks": 1},
            {"crew": "system", "tasks": 2},
        ]
        board["rows"][1]["crews"] = [
            {"crew": "opus", "tasks": 40, "effort_estimate": "high"},
            {"crew": "opus@medium", "tasks": 8},
        ]
        board["rows"][2]["crews"] = [
            {"crew": "luna", "tasks": 10, "effort_estimate": None},
        ]
        # The model row's own numbers stay the fixture's, not the crew-task sum.
        self.assertEqual((board["rows"][0]["units"], board["rows"][0]["score"]), (60, 120.0))

        # A bare key pools the model's efforts: it is the crew name alone, never effort unknown, whatever an older estimate says.
        haiku = build.rank_crew_entries(board["rows"][0])
        self.assertEqual([(item["label"], item["tasks"]) for item in haiku],
                         [("haiku", 590), ("haiku@xhigh", 1)])
        opus = build.rank_crew_entries(board["rows"][1])
        self.assertEqual([(item["label"], item["tasks"]) for item in opus],
                         [("opus", 40), ("opus@medium", 8)])
        self.assertEqual([item["label"] for item in build.rank_crew_entries(board["rows"][2])],
                         ["luna"])
        # Snapshots from before estimates read the same way, and still hide system.
        legacy = build.rank_crew_entries({"crews": [
            {"crew": "sol", "tasks": 861}, {"crew": "sol@high", "tasks": 10},
            {"crew": "sol@xhigh", "tasks": 4}, {"crew": "system", "tasks": 2},
            {"crew": "crew unknown", "tasks": 1},
        ]})
        self.assertEqual([item["label"] for item in legacy],
                         ["sol", "sol@high", "sol@xhigh"])
        # The recorded label keeps its own tasks; a repeated bare crew is one label.
        repeated = build.rank_crew_entries({"crews": [
            {"crew": "sol", "tasks": 3, "effort_estimate": "medium"},
            {"crew": "sol", "tasks": 2, "effort_estimate": "medium"},
            {"crew": "sol@high", "tasks": 1},
        ]})
        self.assertEqual([(item["label"], item["tasks"]) for item in repeated],
                         [("sol", 5), ("sol@high", 1)])
        self.assertTrue(all("estimated" not in item for item in repeated))

        doc = build.render_ranking_body(scorecards(), "2026-11-08", board)
        self.assertNotIn("system", doc)
        overall = doc[doc.index('data-group="overall"'):doc.index('data-group="implementers"')]
        self.assertIn('<span class="podium-crews">haiku: xhigh</span>', overall)
        self.assertIn('<span class="podium-crews">opus: medium</span>', overall)
        self.assertIn('<span class="podium-crews">luna</span>', overall)
        self.assertIn('<span class="ml-crews">haiku: xhigh</span>', overall)
        self.assertIn('<span class="ml-crews">opus: medium</span>', overall)
        self.assertNotIn("(est.)", overall)
        self.assertNotIn("est-note", overall)
        # The breakdown keeps each key's tasks: the pooled bare key, then the one carrying an effort.
        self.assertIn("<dd>haiku 590 · haiku@xhigh 1</dd>", overall)
        self.assertNotIn("effort unknown", overall)
        self.assertIn('<span class="ml-units">60</span>', overall)

    def test_without_rank_json_overall_shows_a_notice_and_the_index_podium(self):
        data = all_roles_scorecards()
        doc = build.render_ranking_body(data, "2026-11-08")
        overall = doc[doc.index('data-group="overall"'):doc.index('data-group="implementers"')]
        notice = re.findall(r'<p class="board-note rank-missing"[^>]*>(.*?)</p>', overall)
        self.assertEqual(notice, ["Model rank: this snapshot has no rank board; it appears with the next snapshot."])
        self.assertNotIn('class="model-board"', doc)
        self.assertNotIn("Not ranked yet", doc)
        self.assertIn("This snapshot has no Model rank, so the podium follows the All-roles index.", overall)
        podium = re.search(r'<ol class="podium" aria-label="Top three models by the All-roles index">.*?</ol>', overall, re.S)
        self.assertEqual(re.findall(r'<span class="podium-model">.*?<span>([^<]+)</span>', podium.group(0)),
                         ["model-ir", "model-ip", "model-all"])
        self.assertIn('id="all-roles"', overall)
        self.assertIn('id="crews-implementers"', doc)
        self.assertIn('id="tiers"', doc)

    def test_method_and_windows_describes_both_methodologies(self):
        doc = build.render_ranking_body(all_roles_scorecards(), "2026-11-08", rank_board())
        method = plain(doc[doc.index('id="method"'):])
        self.assertIn("Model rank", method)
        for needle in ("80% confidence share a band", "Cost orders models inside a band",
                       "Only eligible models are ranked; Orbit's rule: orbit fixture rule", "live: it ends at the snapshot",
                       "provisional", "two to six weeks old", "window estimate",
                       "without ranks or a podium"):
            self.assertIn(needle, method.replace("&#x27;", "'"))
        self.assertIn("All-roles index", method)
        self.assertIn("rescaled", method)
        self.assertNotIn("counts as 100", doc)

    def test_eligibility_rule_falls_back_to_the_board_numbers(self):
        board_data = rank_board()
        del board_data["eligibility_rule"]
        self.assertEqual(build.eligibility_rule(board_data),
                         "At least 30 implemented tasks spanning at least 2 assessed tiers with at least 5 tasks each.")
        board_data["rules"]["min_tiers"] = 1
        self.assertEqual(build.eligibility_rule(board_data), "At least 30 implemented tasks, with at least 5 in one assessed tier.")
        # A row without Orbit's reason falls back to the progress the rules imply.
        board_data["rows"][3]["ineligible_reason"] = None
        self.assertEqual(build.gate_progress(board_data["rows"][3], board_data["rules"])[1], "9 of 30 tasks")
        # Orbit's single-tier flag shows beside the model.
        board_data["rows"][0]["single_tier"] = "hard"
        self.assertIn('<span class="ml-flag">single tier: hard</span>', build.models_board(board_data))

    def test_rank_board_must_be_managed_30d_with_agreeing_live_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.assertIsNone(build.load_rank(directory))
            (directory / "rank.json").write_text(json.dumps(rank_board()), encoding="utf-8")
            self.assertIs(build.load_rank(directory)["live"], True)
            # A snapshot written before the live board carries a settled one.
            settled = rank_board()
            settled["live"] = settled["provisional"] = False
            (directory / "rank.json").write_text(json.dumps(settled), encoding="utf-8")
            self.assertIs(build.load_rank(directory)["live"], False)
            settled_doc = build.render_ranking_body(scorecards(), "2026-11-08", settled)
            self.assertIn("Settled window", settled_doc)
            self.assertNotIn("live model rank", settled_doc)
            for key, value in (("live", False), ("provisional", False), ("execution", "all")):
                board_data = rank_board()
                board_data[key] = value
                (directory / "rank.json").write_text(json.dumps(board_data), encoding="utf-8")
                with self.assertRaises(SystemExit):
                    build.load_rank(directory)

    def test_crews_by_role_is_one_shared_renderer_over_a_snapshot_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "2026-11-08"
            directory.mkdir()
            data = scorecards()
            data["implementers"]["fleet_average"] = 120.0
            (directory / "scorecards.json").write_text(json.dumps(data), encoding="utf-8")
            page_doc = build.render_ranking_body(data, "2026-11-08")
            for role in ("implementers", "reviewers", "pilots"):
                shared = build.render_crews_by_role(directory, role)
                self.assertTrue(shared.startswith(f'<section class="crews-by-role" id="crews-{role}"'))
                # The page embeds exactly what the shared renderer returns.
                self.assertIn(shared, page_doc)
            implementers = build.render_crews_by_role(directory, "implementers")
            self.assertIn('id="implementer-crews"', implementers)
            self.assertIn('id="tiers"', implementers)
            self.assertIn('class="fleet-mark"', implementers)
            self.assertIn('class="tiles takeaways"', implementers)
            # ORB-23665: the stacked form (the weekly note's body) gives every role
            # once, in order, under a plain heading, with no toggle of its own.
            stacked = build.render_crews_by_role(directory)
            self.assertNotIn("<nav", stacked)
            self.assertNotIn("role-pills", stacked)
            headings = re.findall(r'<h2 id="crews-(\w+)-title">([^<]+)</h2>', stacked)
            self.assertEqual(headings, [("implementers", "Implementers"), ("reviewers", "Reviewers"), ("pilots", "Pilots")])
            self.assertNotIn('id="tiers"', stacked)
            for element_id in ("implementer-crews", "reviewers-provisional", "pilot-crews"):
                self.assertEqual(stacked.count(f'id="{element_id}"'), 1, element_id)
            with self.assertRaises(SystemExit):
                build.render_crews_by_role(directory, "orchestrators")

    def test_role_tabs_are_the_only_role_navigation(self):
        # ORB-23665: each role tab rendered Crews by role with its own
        # Implementers/Reviewers/Pilots toggle under the page's tab strip.
        doc = build.render_ranking_body(scorecards(), "2026-11-08", rank_board())
        self.assert_one_role_navigation(doc)

    def assert_one_role_navigation(self, doc):
        self.assertNotIn("role-pills", doc)
        self.assertEqual(doc.count("<nav"), 1)
        self.assertEqual(len(re.findall(r'<nav class="group-nav" aria-label="Ranking views">', doc)), 1)
        self.assertEqual(re.findall(r'data-tab="(\w+)"', doc), ["overall", "implementers", "reviewers", "pilots"])
        groups = re.split(r'<div class="role-group" data-group="', doc)[1:]
        self.assertEqual([g.split('"', 1)[0] for g in groups], ["overall", "implementers", "reviewers", "pilots"])
        for group in groups:
            body = group[:group.find('<section class="method-cards"')] if 'method-cards' in group else group
            self.assertNotIn("<nav", body)
            self.assertNotIn('href="#crews-', body)
        # Without JavaScript the panels stack: each role's boards appear once.
        for element_id in ("crews-implementers", "crews-reviewers", "crews-pilots", "implementer-crews",
                           "tiers", "reviewers-provisional", "reviewers-settled", "pilot-crews"):
            self.assertEqual(doc.count(f'id="{element_id}"'), 1, element_id)
        self.assertEqual(doc.count('class="tiles takeaways"'), 3)

    def test_score_explanation_appears_once_per_board(self):
        doc = build.render_ranking_body(scorecards(), "2026-11-08", rank_board())
        boards = re.findall(r'<section class="board"[^>]*id="([^"]+)"', doc)
        self.assertIn("reviewers-provisional", boards)
        self.assertIn("reviewers-settled", boards)
        for element_id in ("implementer-crews", "reviewers-provisional", "reviewers-settled", "pilot-crews"):
            block = section(doc, element_id)
            self.assertEqual(block.count("Score: per 100"), 1, element_id)
            self.assertEqual(len(re.findall(r"credit for", block)), 1, element_id)

    def test_ranking_boards_collapse_at_their_own_width_not_the_phone_breakpoint(self):
        # ORB-23658: between 561px and desktop the Overall table squeezed its Model
        # column to a few letters. Every ranking board now collapses on its own box
        # (a container query), at a width measured to keep names on one line.
        css = (ROOT / "public" / "assets" / "analytics-ranking.css").read_text(encoding="utf-8")
        self.assertIn(".ranking-page .role-group, .crews-by-role { container: ranking / inline-size; }", css)
        blocks = {
            int(width): body
            for width, body in re.findall(r"@container ranking \(max-width: (\d+)px\) \{(.*?)\n\}", css, re.S)
        }
        tables = [body for width, body in blocks.items()
                  if ".analytics .bar-table, .analytics table.heatmap { display: block;" in body]
        self.assertEqual(len(tables), 1, "one container block stacks the role tables and the heatmap")
        table_width = next(w for w, body in blocks.items() if body in tables)
        self.assertGreater(table_width, 800, "the Overall table needs ~841px with names on one line")
        self.assertIn(".overall-table", tables[0])
        self.assertTrue(any(".model-line {" in body for body in blocks.values()))
        self.assertTrue(any(".bar-row {" in body for body in blocks.values()))
        # The board layouts no longer switch on the viewport's phone breakpoint.
        for body in re.findall(r"@media \(max-width: \d+px\) \{(.*?)\n\}", css, re.S):
            for selector in (".overall-table", ".model-line", ".bar-row", ".heatmap"):
                self.assertNotIn(selector, body)
        # Above a collapse point names stay whole.
        self.assertRegex(css, r"\.analytics \.bar-table \.crew-name, \.analytics \.bar-table \.crew-model,\n"
                              r"\.rank-list \.crew-name, \.rank-list \.crew-model \{ white-space: nowrap;")
        doc = build.render_ranking_body(all_roles_scorecards(), "2026-11-08", rank_board())
        overall = doc[doc.index('data-group="overall"'):doc.index('data-group="implementers"')]
        self.assertIn('<div class="table"><table class="bar-table overall-table">', overall)
        self.assertIn('class="crews-by-role"', doc)
        self.assertIn('class="model-board"', doc)

    def test_old_agents_urls_redirect_to_ranking(self):
        rules = (ROOT / "public" / "_redirects").read_text(encoding="utf-8").splitlines()
        for line in ("/analytics/agents /ranking/ 301", "/analytics/agents/ /ranking/ 301",
                     "/analytics/agents/* /ranking/ 301"):
            self.assertIn(line, rules)

    def test_build_writes_the_page_from_the_newest_snapshot(self):
        env = os.environ.copy()
        env["UV_CACHE_DIR"] = str(ROOT / ".orbit" / "tmp" / "uv-cache")
        proc = subprocess.run(
            ["uv", "run", "--with", "markdown==3.8.2", "python3", "build.py"],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        directory = build.latest_analytics_dir()
        self.assertIn(f"from {directory.name}", proc.stdout)
        page = (ROOT / "public" / "ranking" / "index.html").read_text(encoding="utf-8")
        self.assertIn(f'Snapshot <time datetime="{directory.name}">{directory.name}</time>', page)
        for label in ("Overall", "Implementers", "Reviewers", "Pilots"):
            self.assertIn(f'data-tab="{label.lower()}"', page)
        self.assert_one_role_navigation(page[page.index('<article class="analytics ranking-page">'):page.index("</article>")])
        # No archive: the old agents pages are gone and redirected.
        self.assertFalse((ROOT / "public" / "analytics" / "agents").exists())
        self.assertFalse(any((ROOT / "public" / "ranking").glob("*/")))
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", "public/ranking/index.html"],
            cwd=ROOT,
        )
        self.assertEqual(ignored.returncode, 0)


if __name__ == "__main__":
    unittest.main()
