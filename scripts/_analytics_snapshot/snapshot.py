"""Snapshot collection, assembly, serialization and replay."""

import json
import pathlib
import subprocess
import sys

from .api import (
    http_json,
    orbit_json,
    scorecard_supports_until,
    workspace_id,
)
from .common import (
    FRICTION_FAMILIES,
    OPTIONAL_KEYS,
    PUBLIC_KEYS,
    RANK_EXECUTION,
    SCHEMA_VERSION,
    SETTLED_UNTIL,
    WINDOW,
    dump,
    empty_dropped,
    experiment_omitted,
)
from .experiments import (
    project_experiments,
)
from .metrics import (
    project_completions,
    project_defects,
    project_diff,
    project_durations,
    project_friction,
    project_outcome_mix,
    project_tokens,
    project_turns,
)
from .rank import (
    project_rank,
)
from .redaction import (
    forbidden_patterns,
    guard,
    host_names,
)
from .reliability import (
    project_reliability,
)
from .scorecards import (
    assemble_scorecards,
)


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
    if isinstance(docs_without_meta.get("rank"), dict):
        windows["rank"] = span(docs_without_meta["rank"])
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
    print("rank", file=sys.stderr)
    rank = http_json(
        dashboard, "/api/agents/rank", {"window": WINDOW, "execution": RANK_EXECUTION, **scope}
    )
    print("experiments", file=sys.stderr)
    listed = orbit_json(["experiment", "list"], workspace)
    experiments = listed.get("experiments") if isinstance(listed, dict) else None
    if not isinstance(experiments, list):
        raise SystemExit("orbit experiment list did not return experiments")
    readouts = []
    for experiment in experiments:
        if not isinstance(experiment, dict):
            continue
        if experiment.get("status") != "concluded" or experiment_omitted(experiment):
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
        rank=rank,
        experiments=readouts,
        generated_at=generated_at,
        version=version,
        workspace=workspace,
    )


def project_all(cards, until_supported, durations, completions, defects, tokens, turns, diff,
                friction, outcome_mix, reliability, experiments, generated_at, version, workspace, rank=None):
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
    projected_experiments = project_experiments(experiments, dropped, patterns, redactions)
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
    if rank is not None:
        docs["rank"] = project_rank(rank, dropped, patterns, redactions)
    docs["meta"] = assemble_meta(docs, generated_at, version, workspace, until_supported, dropped, redactions[0])
    return docs


def write_snapshot(out, docs):
    out.mkdir(parents=True, exist_ok=True)
    raw = out / "raw"
    raw.mkdir(exist_ok=True)
    text = {key: dump(docs[key]) for key in PUBLIC_KEYS if key in docs}
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
    required = set(PUBLIC_KEYS) - set(OPTIONAL_KEYS)
    if not isinstance(docs, dict) or not required <= set(docs) or not set(docs) <= set(PUBLIC_KEYS):
        raise SystemExit("bundle must contain scorecards, metrics, reliability, experiments and meta (rank is optional)")
    return docs


def replay(source, out):
    docs = load_bundle(source)
    guard(docs)
    write_snapshot(pathlib.Path(out), docs)


def generated_now():
    proc = subprocess.run(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], check=True, capture_output=True, text=True)
    return proc.stdout.strip()
