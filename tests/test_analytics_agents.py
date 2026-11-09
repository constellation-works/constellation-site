"""The public agent-scorecards page rendered from a snapshot."""

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


class AgentsPageTest(unittest.TestCase):
    def test_summary_and_descriptions_allow_earlier_settled_window(self):
        data = scorecards()
        self.assertLess(
            data["reviewers"]["settled"]["window"]["until"],
            data["reviewers"]["provisional"]["window"]["until"],
        )
        doc = build.render_agents_page(data, "2026-11-08")
        self.assertIn("2026-09-09T09:11:48Z", section(doc, "reviewers-settled"))
        summary = re.search(r'<p class="summary">(.*?)</p>', doc).group(1)
        self.assertIn("Each scorecard shows its own window.", summary)
        self.assertNotIn("last 30 days", summary.lower())
        for attribute in ('name="description"', 'property="og:description"'):
            description = re.search(rf'<meta {attribute} content="([^"]*)"', doc).group(1)
            self.assertIn("each with its own window", description)
            self.assertNotIn("last 30 days", description.lower())

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
        doc = build.render_agents_page(data, directory.name)
        self.assertIn(f"Snapshot {directory.name}.", doc)
        self.assertIn('href="/notes/crew-rankings-method/"', doc)
        for element_id, payload in (
            ("implementers", data["implementers"]),
            ("reviewers", data["reviewers"]["provisional"]),
            ("reviewers-settled", data["reviewers"]["settled"]),
            ("pilots", data["pilots"]),
            ("tiers", data["implementers_by_tier"]),
        ):
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
        self.assertIn(">Settled<", doc)
        self.assertIn(">unranked<", doc)
        self.assertNotIn("orchestrator-only", doc)
        self.assertIn("Orchestrators are not scored on this page.", doc)
        for gap in ("model unknown", "crew unknown", "crew unavailable"):
            self.assertNotIn(gap, doc)
        for needle in ("ORB-", "jrun-", "/home/", "ws_"):
            self.assertNotIn(needle, doc)
        self.assertNotIn("dropped", doc)
        # Progressive enhancement: tabs and toggle come from analytics.js.
        self.assertIn("/assets/analytics.js?v=", doc)
        self.assertIn("/assets/analytics.css?v=", doc)
        self.assertIn('<nav class="group-nav" aria-label="Roles">', doc)
        self.assertIn('class="board-toggle" role="group" aria-label="Review window" hidden', doc)

    def test_live_snapshot_heatmap_keeps_models_apart(self):
        # luna on gpt-6-luna and luna on gpt-6.1-luna are separate rows, as on
        # the overall board: summing every luna cell would read 654 low tasks.
        directory = build.latest_analytics_dir()
        data = json.loads((directory / "scorecards.json").read_text(encoding="utf-8"))
        slots, _min_support = build.tier_slots(data["implementers_by_tier"])
        low = slots["low"]
        expected = sum(
            cell["n"] for cell in data["implementers_by_tier"]["cells"]
            if cell["tier"] == "low" and cell["crew"] == "luna" and cell["model"] == "gpt-6-luna"
        )
        self.assertEqual(low[("luna", "gpt-6-luna")]["units"], expected)
        self.assertEqual(low[("luna", "gpt-6.1-luna")]["units"], 1)
        doc = build.render_agents_body(data, directory.name)
        tiers = section(doc, "tiers")
        self.assertIn(f"{expected:,} tasks", tiers)
        self.assertNotIn(f"{expected + 1:,} tasks", tiers)

    def test_takeaways_are_derived_from_the_tiers(self):
        directory = build.latest_analytics_dir()
        data = json.loads((directory / "scorecards.json").read_text(encoding="utf-8"))
        doc = build.render_agents_body(data, directory.name)
        cards = re.search(r'<ul class="tiles takeaways".*?</ul>', doc).group(0)
        slots, _ = build.tier_slots(data["implementers_by_tier"])
        for tier in build.TIER_ORDER:
            leaders = [slot for slot in slots[tier].values() if slot["rank"] == 1]
            if leaders:
                self.assertIn(leaders[0]["crew"], cards)
        sized = [slot for tier in build.TIER_ORDER for slot in slots[tier].values() if slot["rank"] is not None]
        weakest = min(sized, key=lambda slot: slot["score"])
        self.assertIn(f'{weakest["crew"]} {weakest["score"]:.1f}', cards)
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
        doc = build.render_agents_body(data, "2026-11-08")
        overall = section(doc, "implementers")

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
        doc = build.render_agents_body(scorecards(), "2026-11-08")
        implementers = section(doc, "implementers")
        self.assertIn("haiku", implementers)
        self.assertIn("per 100 implemented tasks", implementers)
        self.assertIn('data-rank="1"', implementers)
        self.assertIn("tiny", implementers)
        self.assertIn('data-rank="unranked"', implementers)
        for gap in ("crew unavailable", "model unknown", "crew unknown", "orchestrator-only", "secret-model"):
            self.assertNotIn(gap, doc)
        self.assertIn("1,387 reviews in this window are still provisional.", doc)
        self.assertIn(">Provisional<", section(doc, "reviewers"))
        settled = section(doc, "reviewers-settled")
        self.assertIn(">Settled<", settled)
        self.assertIn("2026-09-09T09:11:48Z", settled)
        self.assertIn("per 100 settled reviews", settled)
        self.assertIn("per 100 assessed tasks", section(doc, "pilots"))

    def test_tier_heatmap_sums_types_and_reranks(self):
        doc = build.render_agents_body(scorecards(), "2026-11-08")
        tiers = section(doc, "tiers")
        self.assertIn('datetime="2026-10-09T09:11:25Z"', tiers)
        self.assertIn("Each tier's fleet rate is 100", tiers)
        self.assertIn('id="implementers-low"', tiers)
        slots, min_support = build.tier_slots(scorecards()["implementers_by_tier"])
        self.assertEqual(min_support, 10)
        low = slots["low"]
        self.assertEqual(low[("haiku", "claude-haiku-5-5")]["units"], 12)
        self.assertEqual(low[("haiku", "claude-haiku-5-5")]["rank"], 2)
        self.assertEqual(low[("opus", "claude-opus-5-5")]["rank"], 1)
        self.assertIsNone(low[("thin", "gpt-thin")]["rank"])
        self.assertNotIn(("gap", "model unknown"), low)

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

    def test_settled_board_hidden_when_absent(self):
        data = scorecards()
        data["reviewers"]["settled"] = None
        doc = build.render_agents_body(data, "2026-11-08")
        self.assertNotIn("reviewers-settled", doc)
        self.assertNotIn(">Settled<", doc)
        self.assertNotIn("2026-09-09T09:11:48Z", doc)
        self.assertIn(">Provisional<", doc)

    def test_refuses_a_window_other_than_30d(self):
        data = scorecards()
        data["pilots"]["window"]["key"] = "7d"
        with self.assertRaises(SystemExit):
            build.render_agents_body(data, "2026-11-08")

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
            for slug in ("agents", "metrics", "reliability", "experiments"):
                self.assertIn(f'href="/analytics/{slug}/"', document)
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
        page = (ROOT / "public" / "analytics" / "agents" / "index.html").read_text(encoding="utf-8")
        self.assertIn(f"Snapshot {directory.name}.", page)
        self.assertIn("Implementers", page)
        self.assertIn("Reviewers", page)
        self.assertIn("Pilots", page)
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", "public/analytics/agents/index.html"],
            cwd=ROOT,
        )
        self.assertEqual(ignored.returncode, 0)


if __name__ == "__main__":
    unittest.main()
