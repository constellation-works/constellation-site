"""Shared fixtures and the path-loaded analytics snapshot entry point."""

import importlib.util
from pathlib import Path


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
