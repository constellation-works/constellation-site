"""Regression coverage for analytics snapshot path redaction (ORB-23163)."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("analytics_snapshot", ROOT / "scripts/analytics_snapshot.py")
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)

HOSTS = ["dk-server-1", "dk-server-2"]
PATH_SAMPLES = [
    "</srv/acme/customer>",
    "</srv/acme/customer.txt>",
    "</my_el/customer.txt>",
    "</my.el/customer>",
    "</home/private/customer.txt>",
    "<~/secret/notes.txt>",
    "<code>/srv/acme/customer</code>",
    "/srv/acme/customer.txt",
    "/root/acme/customer.txt",
    "/mnt/acme/customer.txt",
    "/data/acme/customer.txt",
    "/home/private/customer.txt",
    "/home/daniel/note.txt",
    r"C:\acme\customer.txt",
    "C:/acme/customer.txt",
    r"\\server\share\customer.txt",
    "crates/core/customer.rs",
    "scripts/analytics_snapshot.py",
    "./src/lib.rs",
    "../outside/secret.txt",
    "~/private/customer.txt",
    "/workspace",
    "/srv",
    "/Makefile",
    "file:///etc/passwd",
    "file:///home/daniel/secret/x.txt",
    "FILE:///Users/dan/x",
]
RELATIVE_LEFT = ["src/Makefile"]
API_SOURCES = [
    "GET /api/diagnostics/implement_one?since=30d&outcome=succeeded",
    "GET /api/diagnostics/completions?since=30d",
    "GET /api/metrics/reliability?window=30d",
    "GET /api/tasks/completion-by-complexity",
]


def minimal_docs(hypothesis="clean hypothesis"):
    return {
        "scorecards": {
            "roles": list(snapshot.ROLES),
            "reviewers": {"provisional": {"provisional": True}, "settled": None},
        },
        "metrics": {"source": API_SOURCES[0], "tokens": {"source": API_SOURCES[1]}},
        "reliability": {"source": API_SOURCES[2]},
        "experiments": {
            "source": "orbit experiment list --json; orbit experiment readout --json <id>",
            "experiments": [{"status": "concluded", "hypothesis": hypothesis, "enrollment": {"analysed": 20}}],
        },
        "meta": {"reviewer_settled": False},
    }


def concluded_experiment(text):
    dropped = snapshot.empty_dropped()
    patterns = snapshot.forbidden_patterns(HOSTS)
    redactions = [0]
    readout = {
        "as_of": "2026-11-08T00:00:00Z",
        "experiment": {"status": "concluded", "started_at": "2026-10-01T00:00:00Z"},
        "enrollment": {"analysed": 20, "unreadable": 0},
        "arms": [{"name": "treatment", "control": False, "weight": 1, "n": 10,
                  "segments": [{"segment": 1, "n": 10}], "crew_mix": [{"crew": "opus", "tasks": 8}]}],
        "metrics": [],
        "verdict": {"state": "adopt", "arm": "treatment", "label": text,
                    "horizon_reached": True, "reasons": [text]},
        "warnings": [],
    }
    definition = {
        "id": "exp-alpha", "name": text, "status": "concluded", "mode": "live",
        "hypothesis": text, "primary_metric": "delivery_done", "concluded_arm": "treatment",
        "min_sample": 10, "max_days": 14, "segment": 1,
        "population": {"complexity": ["low"]}, "guardrails": {},
        "updated_at": "2026-11-01T00:00:00Z",
    }
    return snapshot.project_experiment(definition, readout, dropped, patterns, redactions)


class PathRedactionTest(unittest.TestCase):
    def test_closing_tag_path_exception_and_bare_path(self):
        patterns = snapshot.forbidden_patterns(HOSTS)
        text = "see </workspace>, </home> and </srv> alongside /workspace"
        self.assertEqual(snapshot.sanitize(text, patterns, [0]),
                         "see </workspace>, </home> and </srv> alongside [redacted]")
        snapshot.guard(minimal_docs("see </workspace>, </home> and </srv>"), HOSTS)

    def test_sanitize_redacts_paths_outside_old_root_list(self):
        patterns = snapshot.forbidden_patterns(HOSTS)
        for leaked in PATH_SAMPLES:
            with self.subTest(leaked=leaked):
                redactions = [0]
                cleaned = snapshot.sanitize(f"check {leaked} end", patterns, redactions)
                self.assertNotIn(leaked, cleaned)
                self.assertIn("[redacted]", cleaned)
                self.assertGreaterEqual(redactions[0], 1)

    def test_sanitize_preserves_api_sources_and_ordinary_slashes(self):
        patterns = snapshot.forbidden_patterns(HOSTS)
        for source in API_SOURCES:
            self.assertEqual(snapshot.sanitize(source, patterns, [0]), source)
        for prose in ["delivered on 3/4 runs (haiku/luna)", "and/or", "crew / model", "haiku / claude-opus-5-5",
                      "<b>ok</b> <span>done</span>", "</my_el>", "</my.el>", "<my_el>ok</my_el> <my.el>ok</my.el>"]:
            with self.subTest(prose=prose):
                self.assertEqual(snapshot.sanitize(prose, patterns, [0]), prose)

    def test_guard_accepts_closing_tags_with_underscore_or_dot_names(self):
        snapshot.guard(minimal_docs("see </my_el> and </my.el> in prose"), HOSTS)

    def test_sanitize_leaves_relative_paths_without_extension(self):
        patterns = snapshot.forbidden_patterns(HOSTS)
        for relative in RELATIVE_LEFT:
            with self.subTest(relative=relative):
                self.assertEqual(snapshot.sanitize(f"check {relative} end", patterns, [0]),
                                 f"check {relative} end")

    def test_projection_redacts_free_text_and_preserves_aggregates(self):
        for leaked in PATH_SAMPLES:
            with self.subTest(leaked=leaked):
                experiment = concluded_experiment(f"Investigate {leaked} now")
                blob = json.dumps(experiment)
                self.assertNotIn(leaked, blob)
                self.assertIn("[redacted]", blob)
                self.assertEqual(experiment["enrollment"], {"analysed": 20, "unreadable": 0})
                self.assertEqual(experiment["arms"][0]["n"], 10)
                self.assertEqual(experiment["arms"][0]["crew_mix"], [{"crew": "opus", "tasks": 8}])

    def test_guard_rejects_paths_and_accepts_api_sources(self):
        snapshot.guard(minimal_docs(), HOSTS)
        for leaked in PATH_SAMPLES:
            with self.subTest(leaked=leaked):
                with self.assertRaises(SystemExit):
                    snapshot.guard(minimal_docs(f"Investigate {leaked}"), HOSTS)

    def test_replay_rejects_tampered_bundle_and_preserves_clean_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle.json"
            bundle.write_text(snapshot.dump(minimal_docs()))
            out = root / "out"
            snapshot.replay(str(bundle), str(out))
            for source in API_SOURCES[:1]:
                self.assertIn(source, (out / "metrics.json").read_text())
            self.assertIn(API_SOURCES[2], (out / "reliability.json").read_text())
            bundle.write_text(snapshot.dump(minimal_docs("see crates/core/customer.rs")))
            bad_out = root / "bad-out"
            with self.assertRaises(SystemExit):
                snapshot.replay(str(bundle), str(bad_out))
            self.assertFalse((bad_out / "experiments.json").exists())


def experiment_pair(ident, name, status="concluded"):
    definition = {
        "id": ident, "name": name, "status": status, "mode": "live",
        "hypothesis": "clean hypothesis", "primary_metric": "delivery_done", "concluded_arm": "treatment",
        "min_sample": 10, "max_days": 14, "segment": 1, "population": {"complexity": ["low"]},
        "guardrails": {}, "updated_at": "2026-11-01T00:00:00Z",
    }
    readout = {
        "as_of": "2026-11-08T00:00:00Z",
        "experiment": {"status": "concluded", "started_at": "2026-10-01T00:00:00Z"},
        "enrollment": {"analysed": 20, "unreadable": 0},
        "arms": [{"name": "treatment", "control": False, "weight": 1, "n": 10,
                  "segments": [{"segment": 1, "n": 10}], "crew_mix": [{"crew": "opus", "tasks": 8}]}],
        "metrics": [],
        "verdict": {"state": "adopt", "arm": "treatment", "label": "adopt", "horizon_reached": True, "reasons": []},
        "warnings": [],
    }
    return definition, readout


class ExperimentOmitTest(unittest.TestCase):
    def test_omit_list_has_a_one_line_public_reason_per_id(self):
        self.assertEqual(snapshot.EXPERIMENT_OMITS["exp-2b6d910d"],
                         "void: treatment not reliably applied and the explorer was removed mid-run")
        for ident, reason in snapshot.EXPERIMENT_OMITS.items():
            with self.subTest(ident=ident):
                self.assertIsNotNone(snapshot.SAFE_ID.fullmatch(ident))
                self.assertTrue(reason.strip())
                self.assertNotIn("\n", reason)

    def test_omitted_experiments_are_counted_and_never_projected(self):
        for ident, name in (
            ("exp-2b6d910d", "hard-tier-explore-first"),
            ("exp-00c7ef1f", "opus-hard-effort-check"),
        ):
            with self.subTest(ident=ident):
                patterns = snapshot.forbidden_patterns(HOSTS)
                dropped = snapshot.empty_dropped()
                redactions = [0]
                omitted_definition, omitted_readout = experiment_pair(ident, name)
                running_definition, _ = experiment_pair("exp-run", "still running", status="running")
                kept_definition, kept_readout = experiment_pair("exp-alpha", "kept")
                pairs = [
                    (omitted_definition, omitted_readout),
                    (omitted_definition, None),  # collect() skips the readout of an omitted id
                    (running_definition, None),
                    (kept_definition, kept_readout),
                ]
                projected = snapshot.project_experiments(pairs, dropped, patterns, redactions)
                self.assertEqual([item["id"] for item in projected], ["exp-alpha"])
                self.assertEqual(dropped["experiments_omitted"], 3)
                self.assertNotIn(ident, json.dumps(projected))
                self.assertNotIn(name, json.dumps(projected))

    def test_guard_refuses_an_omitted_experiment_in_the_public_snapshot(self):
        for ident in snapshot.EXPERIMENT_OMITS:
            with self.subTest(ident=ident):
                docs = minimal_docs()
                snapshot.guard(docs, HOSTS)
                docs["experiments"]["experiments"].append(
                    {"id": ident, "status": "concluded", "hypothesis": "clean hypothesis"})
                with self.assertRaises(SystemExit):
                    snapshot.guard(docs, HOSTS)


def rank_payload(**overrides):
    payload = {
        "window": "30d", "since": "2026-10-10T07:34:21Z", "until": "2026-11-09T07:34:21Z",
        "settle_lag": "14d", "execution": "managed", "live": True, "provisional": True, "status": "ok",
        "measures": [{"key": "escaped_regressions", "label": "Escaped regressions", "weight": 30.0, "sign": -1.0,
                      "pillar": "quality", "status": "measured", "units": "implemented tasks",
                      "definition": "Escaped regressions, see /home/daniel/rank.rs", "reason": None}],
        "weights_total": 30.0,
        "rules": {"shrinkage_k": 30.0, "min_tasks": 30, "min_tiers": 2, "min_tier_tasks": 5, "min_eligible_models": 3},
        "unattributed": {"tasks": 3, "crews": [{"crew": "secret-crew", "tasks": 3}]},
        "paired_probabilities": {"gpt-a": {"gpt-b": 0.9}},
        "rows": [
            {"model": "gpt-a", "rank": 1, "rank_label": "1", "band_size": 1, "eligible": True, "units": 40,
             "tasks_by_tier": {"low": 20, "medium": 20}, "score": 110.0, "raw_score": 112.0,
             "interval": {"p10": 105.0, "p90": 115.0}, "z": 1.0,
             "cost": {"ratio": 0.8, "per_task": 1.0, "expected_per_task": 1.25, "coverage": 0.9, "cost_unknown": False},
             "measures": {"escaped_regressions": {"status": "measured", "weight": 30.0, "units": 40,
                                                  "unit": "implemented tasks", "actual": 1.0, "expected": 2.0,
                                                  "residual": 0.1, "contribution": 3.0}},
             "landed_tasks": 39.0, "landed_rate": 0.975,
             "crews": [{"crew": "sol", "tasks": 38}, {"crew": "crew unknown", "tasks": 2}],
             "effort_split": [{"crew": None, "model": "gpt-a", "provider_cost_usd": 1.0}],
             "tiers": [{"tier": "low", "tasks": 20, "score": 108.0, "cost_per_task": 0.5,
                        "cost_coverage": 1.0, "cost_unknown": False}]},
            {"model": "model unknown", "rank": None, "eligible": False, "units": 9},
            {"model": "gpt-thin", "rank": None, "eligible": False, "ineligible_reason": "8 implemented tasks; 30 needed",
             "units": 8, "tasks_by_tier": {"hard": 8}, "score": 120.0, "interval": None},
        ],
    }
    payload.update(overrides)
    return payload


class RankProjectionTest(unittest.TestCase):
    def project(self, payload):
        dropped = snapshot.empty_dropped()
        projected = snapshot.project_rank(payload, dropped, snapshot.forbidden_patterns(HOSTS), [0])
        return projected, dropped

    def test_projection_keeps_public_fields_and_drops_gaps(self):
        rank, dropped = self.project(rank_payload())
        self.assertEqual([row["model"] for row in rank["rows"]], ["gpt-a", "gpt-thin"])
        self.assertEqual(rank["rows"][0]["crews"], [{"crew": "sol", "tasks": 38}])
        self.assertEqual(dropped["rank"], 2)
        self.assertEqual(rank["source"], snapshot.RANK_SOURCE)
        # ORB-23668: the live board, its exact window, and Orbit's rule and reasons.
        self.assertIn("live=true", rank["source"])
        self.assertEqual(rank["window"], {"key": "30d", "since": "2026-10-10T07:34:21Z", "until": "2026-11-09T07:34:21Z"})
        self.assertIs(rank["live"], True)
        self.assertIs(rank["provisional"], True)
        self.assertEqual(rank["execution"], "managed")
        self.assertEqual(rank["rows"][1]["ineligible_reason"], "8 implemented tasks; 30 needed")
        self.assertIsNone(rank["rows"][0]["ineligible_reason"])
        self.assertEqual(rank["eligibility_rule"], "At least 30 implemented tasks spanning at least 2 assessed tiers "
                                                   "with at least 5 tasks each. The board needs 3 such models.")
        blob = json.dumps(rank)
        for private in ("paired_probabilities", "effort_split", '"z"', "secret-crew", "/home/daniel"):
            self.assertNotIn(private, blob)

    def test_eligibility_rule_follows_orbits_rule(self):
        # ORB-23672 moves Orbit to one assessed tier; the sentence follows the numbers.
        rules = {"shrinkage_k": 30.0, "min_tasks": 30, "min_tiers": 1, "min_tier_tasks": 5}
        rank, _ = self.project(rank_payload(rules=rules))
        self.assertEqual(rank["eligibility_rule"], "At least 30 implemented tasks, with at least 5 in one assessed tier.")
        # Orbit's own sentence wins, sanitized.
        rank, _ = self.project(rank_payload(eligibility_rule="30 tasks; one tier of 5+, see /home/daniel/rank.rs"))
        self.assertTrue(rank["eligibility_rule"].startswith("30 tasks; one tier of 5+"))
        self.assertNotIn("/home/daniel", rank["eligibility_rule"])
        rank, _ = self.project(rank_payload(rules={}))
        self.assertIsNone(rank["eligibility_rule"])

    def test_single_tier_flag_is_kept_only_as_a_tier_or_true(self):
        for value, expected in (("hard", "hard"), (True, True), ({"tier": "low"}, "low"), ("<b>", None), (1, None)):
            with self.subTest(value=value):
                payload = rank_payload()
                payload["rows"][0]["single_tier"] = value
                rank, _ = self.project(payload)
                self.assertEqual(rank["rows"][0].get("single_tier"), expected)

    def test_projection_refuses_settled_unmanaged_or_other_windows(self):
        for overrides in ({"live": False}, {"provisional": False}, {"live": False, "provisional": False},
                          {"execution": "all"}, {"window": "7d"}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(SystemExit):
                    self.project(rank_payload(**overrides))

    def test_replay_writes_rank_only_when_the_bundle_has_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle.json"
            docs = minimal_docs()
            bundle.write_text(snapshot.dump(docs))
            snapshot.replay(str(bundle), str(root / "without"))
            self.assertFalse((root / "without" / "rank.json").exists())
            self.assertTrue((root / "without" / "scorecards.json").exists())
            docs["rank"], _ = self.project(rank_payload())
            bundle.write_text(snapshot.dump(docs))
            snapshot.replay(str(bundle), str(root / "with"))
            written = json.loads((root / "with" / "rank.json").read_text())
            self.assertEqual(written["rows"][0]["model"], "gpt-a")
            self.assertIs(written["live"], True)
            # A bundle written before the live board carries a settled one and still replays.
            docs["rank"]["live"] = docs["rank"]["provisional"] = False
            bundle.write_text(snapshot.dump(docs))
            snapshot.replay(str(bundle), str(root / "settled"))
            self.assertIs(json.loads((root / "settled" / "rank.json").read_text())["live"], False)
            # Live without provisional (or the reverse) is refused.
            docs["rank"]["live"] = True
            bundle.write_text(snapshot.dump(docs))
            with self.assertRaises(SystemExit):
                snapshot.replay(str(bundle), str(root / "mixed"))

    def test_system_is_dropped_from_rank_crews_and_counted_with_gaps(self):
        payload = rank_payload()
        payload["rows"][0]["crews"] = [
            {"crew": "sol", "tasks": 800},
            {"crew": "sol@high", "tasks": 10},
            {"crew": "sol@xhigh", "tasks": 4},
            {"crew": "system", "tasks": 2},
            {"crew": "crew unknown", "tasks": 1},
        ]
        rank, dropped = self.project(payload)
        row = rank["rows"][0]
        self.assertEqual(row["crews"], [
            {"crew": "sol", "tasks": 800},
            {"crew": "sol@high", "tasks": 10},
            {"crew": "sol@xhigh", "tasks": 4},
        ])
        # Model numbers stay Orbit's. system is not folded into them.
        self.assertEqual(row["units"], 40)
        self.assertEqual(row["score"], 110.0)
        self.assertEqual(row["rank"], 1)
        # model unknown + crew unknown + system
        self.assertEqual(dropped["rank"], 3)
        self.assertNotIn('"system"', json.dumps(rank))
        self.assertNotIn("system", snapshot.GAP_CREWS)

    def test_bare_rank_crew_carries_no_effort_and_no_estimate(self):
        payload = rank_payload()
        payload["rows"][0]["crews"] = [
            {"crew": "argon", "tasks": 4, "effort_estimate": "high"},
            {"crew": "haiku@xhigh", "tasks": 1},
        ]
        rank, dropped = self.project(payload)
        # A configured effort in the payload is never copied: effort is read from recorded invocations only.
        self.assertEqual(rank["rows"][0]["crews"], [
            {"crew": "argon", "tasks": 4},
            {"crew": "haiku@xhigh", "tasks": 1},
        ])
        self.assertEqual(dropped["rank"], 1)  # the gap model only

    def test_guard_rejects_a_leaked_path_in_rank(self):
        docs = minimal_docs()
        docs["rank"], _ = self.project(rank_payload())
        snapshot.guard(docs, HOSTS)
        docs["rank"]["rows"][1]["ineligible_reason"] = "see /srv/acme/customer.txt"
        with self.assertRaises(SystemExit):
            snapshot.guard(docs, HOSTS)


def scorecard_row(crew, model, effort, label, units=12, rank=1, score=110.0):
    row = {"crew": crew, "model": model, "units": units, "rank": rank, "score": score,
           "below_support": False, "unjudged": False, "label": f"{model} @ {label}"}
    if effort is not ...:
        row["reasoning_effort"] = effort
    if label is not None:
        row["effort_label"] = label
    return row


class EffortIdentityTest(unittest.TestCase):
    """Scorecard rows are one model at one recorded effort (ORB-23657)."""

    def card(self, rows):
        return {"role": "implementers", "window": "30d", "since": "2026-10-10T00:00:00Z",
                "until": "2026-11-09T00:00:00Z", "min_support": 10, "unit": "tasks",
                "fleet_average": 100, "terms": [], "rows": rows}

    def test_rows_copy_reasoning_effort_and_effort_label(self):
        dropped = snapshot.empty_dropped()
        board = snapshot.project_board(self.card([
            scorecard_row("sol", "gpt-6.1-sol", "unknown", "effort unknown", score=132.6),
            scorecard_row("sol", "gpt-6.1-sol", "high", "high", rank=2, score=115.5),
            scorecard_row("argon", "gemini-4-argon-high", None, "provider default", rank=3, score=90.0),
            scorecard_row("bad", "gpt-bad", "<script>", "evil\nlabel", rank=4, score=80.0),
            scorecard_row("legacy", "gpt-legacy", ..., None, rank=5, score=70.0),
        ]), False, dropped, "implementers")
        rows = {(row["crew"], row.get("reasoning_effort")): row for row in board["rows"]}
        self.assertEqual(rows[("sol", "unknown")]["effort_label"], "effort unknown")
        self.assertEqual(rows[("sol", "high")]["effort_label"], "high")
        # No recorded effort: the label is kept, the null effort is not copied.
        self.assertEqual(rows[("argon", None)]["effort_label"], "provider default")
        self.assertNotIn("reasoning_effort", rows[("argon", None)])
        # Values outside the allowlists are dropped, not published.
        self.assertNotIn("effort_label", rows[("bad", None)])
        self.assertNotIn("reasoning_effort", rows[("bad", None)])
        # A row from before the split carries neither field.
        self.assertNotIn("effort_label", rows[("legacy", None)])
        # The composite scorecard label is not copied.
        self.assertTrue(all("label" not in row for row in board["rows"]))

    def test_by_tier_cells_copy_reasoning_effort_and_effort_label(self):
        dropped = snapshot.empty_dropped()
        cells = snapshot.project_cells({
            "min_support": 10, "window": "30d", "since": "2026-10-10T00:00:00Z", "until": "2026-11-09T00:00:00Z",
            "cells": [
                {"tier": "low", "type": "ui", "crew": "sol", "model": "gpt-6.1-sol", "n": 12, "crew_mean": 120,
                 "reasoning_effort": "high", "effort_label": "high", "label": "gpt-6.1-sol @ high"},
                {"tier": "low", "type": "ui", "crew": "sol", "model": "gpt-6.1-sol", "n": 12, "crew_mean": 130,
                 "reasoning_effort": "unknown", "effort_label": "effort unknown"},
                {"tier": "low", "type": "ui", "crew": "old", "model": "gpt-old", "n": 12, "crew_mean": 90},
            ],
        }, dropped)["cells"]
        self.assertEqual(
            [(cell["crew"], cell.get("reasoning_effort"), cell.get("effort_label"), cell["rank"]) for cell in cells],
            [("sol", "unknown", "effort unknown", 1), ("sol", "high", "high", 2), ("old", None, None, 3)],
        )
        self.assertTrue(all("label" not in cell for cell in cells))

    def docs_with(self, rows, board="implementers"):
        docs = minimal_docs()
        dropped = snapshot.empty_dropped()
        projected = snapshot.project_board(self.card(rows), board == "reviewers", dropped, board)
        if board == "reviewers":
            docs["scorecards"]["reviewers"]["provisional"] = projected
        else:
            docs["scorecards"][board] = projected
        return docs

    def test_guard_accepts_one_crew_and_model_at_two_efforts(self):
        snapshot.guard(self.docs_with([
            scorecard_row("sol", "gpt-6.1-sol", "unknown", "effort unknown"),
            scorecard_row("sol", "gpt-6.1-sol", "high", "high", rank=2),
            scorecard_row("argon", "gemini-4-argon-high", None, "provider default", rank=3),
        ]), HOSTS)

    def test_guard_fails_two_rows_with_the_same_crew_model_and_effort(self):
        for board in ("implementers", "reviewers", "pilots"):
            for effort, label in (("high", "high"), (..., None)):
                with self.subTest(board=board, effort=effort):
                    docs = self.docs_with([
                        scorecard_row("sol", "gpt-6.1-sol", effort, label, score=132.6),
                        scorecard_row("sol", "gpt-6.1-sol", effort, label, rank=2, score=115.5),
                    ], board)
                    with self.assertRaises(SystemExit) as raised:
                        snapshot.guard(docs, HOSTS)
                    self.assertIn("two rows for crew sol, model gpt-6.1-sol", str(raised.exception))

    def test_guard_fails_a_replayed_bundle_that_dropped_the_effort(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "bundle.json"
            docs = self.docs_with([
                scorecard_row("sol", "gpt-6.1-sol", "unknown", "effort unknown"),
                scorecard_row("sol", "gpt-6.1-sol", "high", "high", rank=2),
            ])
            for row in docs["scorecards"]["implementers"]["rows"]:
                del row["reasoning_effort"]
                del row["effort_label"]
            bundle.write_text(snapshot.dump(docs))
            with self.assertRaises(SystemExit):
                snapshot.replay(str(bundle), str(Path(directory) / "out"))
            self.assertFalse((Path(directory) / "out" / "scorecards.json").exists())

    def test_new_snapshots_carry_no_effort_estimate(self):
        # A row or cell that arrives with an effort_estimate (an older snapshot) is not copied.
        dropped = snapshot.empty_dropped()
        board = snapshot.project_board(self.card([
            dict(scorecard_row("sol", "gpt-6.1-sol", "unknown", "effort unknown", score=132.6),
                 effort_estimate="high"),
            scorecard_row("sol", "gpt-6.1-sol", "high", "high", rank=2, score=115.5),
            scorecard_row("argon", "gemini-4-argon-high", "unknown", "effort unknown", rank=3, score=90.0),
            scorecard_row("argon", "gemini-4-argon-high", None, "provider default", rank=4, score=80.0),
        ]), False, dropped, "implementers")
        rows = [(row["crew"], row.get("reasoning_effort")) for row in board["rows"]]
        self.assertEqual(rows, [("sol", "unknown"), ("sol", "high"),
                                ("argon", "unknown"), ("argon", None)])
        self.assertTrue(all("effort_estimate" not in row for row in board["rows"]))
        cells = snapshot.project_cells({
            "min_support": 10, "window": "30d",
            "cells": [{"tier": "low", "type": "ui", "crew": "sol", "model": "gpt-6.1-sol", "n": 12,
                       "crew_mean": 120, "reasoning_effort": "unknown", "effort_label": "effort unknown",
                       "effort_estimate": "high"}],
        }, dropped)["cells"]
        self.assertNotIn("effort_estimate", cells[0])
        self.assertEqual(cells[0]["effort_label"], "effort unknown")

    def test_no_crew_configuration_is_read_for_effort(self):
        self.assertFalse(hasattr(snapshot, "crew_effort_estimates"))
        self.assertFalse(hasattr(snapshot, "crews_needing_estimates"))
        self.assertFalse(hasattr(snapshot, "rank_bare_crews"))


if __name__ == "__main__":
    unittest.main()
