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
``provisional_terms``, ``stats`` (``key``, ``label``, ``value``),
``reasoning_effort`` and ``effort_label`` (a scorecard row is one model at one
recorded effort, so these are part of the row's identity; ``unknown`` stays
``unknown``; no effort is ever read from crew configuration, because it
changes over time), and a usage sum from that row's ``effort_breakdown``
(invocations, duration, tokens, cost, reasoning efforts). By-tier cells copy
``tier``, ``type``, ``crew``, ``model``, ``reasoning_effort``,
``effort_label``, ``n``, ``units``, ``score``, ``raw``, ``crew_mean`` and a
rank within the tier and type once ``n`` reaches ``min_support``. The guard
refuses a board with two rows for the same crew, model and reasoning effort.

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
each experiment whose ``status`` is ``concluded`` and whose id is not in
``EXPERIMENT_OMITS``, ``orbit experiment readout --json <id>``. Running, paused,
draft and abandoned experiments, and the experiments in ``EXPERIMENT_OMITS``,
are counted in ``dropped.experiments_omitted`` and left out. Copied: identity
(id, name, hypothesis, primary metric, concluded arm, mode, sample bounds, times),
arms (weight, n, segments, crew mix, usage), enrollment counts, per-metric
arm outcomes and intervals, differences versus control, guardrail estimates,
sample-ratio headline, lagging counts, verdict, and warning kinds without
their messages. Salts, overlays, assignment digests and run digests are not
copied. Free text (hypothesis, name, verdict reasons and labels) is copied
only after task ids, run ids, file paths, host names and workspace ids
(``ws_…``) are replaced with ``[redacted]``. File paths are matched by
shape, not by a list of root names: Unix absolute paths (including a bare
single segment such as ``/workspace``), any ``file:`` URI, Windows drive or
UNC path, home-relative path, and repository-relative path whose final
component names a file (or which descends at least two directories) is
redacted. A single-segment path in closing-tag form such as ``</workspace>``
is preserved when its name matches the closing-tag syntax, because it is
indistinguishable from a tag; do not rely on redaction for such text.
A relative path with no extension that descends fewer than two
directories (``src/Makefile``) is left as it is by design. Public API source
labels (``GET /api/…``) are not file paths and are preserved.

Rank (``rank.json``): ``GET /api/agents/rank?window=30d&execution=managed``
of the named workspace, the settled implementer-model rank board. The
ranked 30 days end at the settled cutoff (``until`` minus ``settle_lag``,
14 days by default), so ``live`` and ``provisional`` are both false. The
live view is never requested: it is provisional and is not published.
Copied: the settled window, settle lag, qualification rules, Orbit's
eligibility rule as one sentence (``eligibility_rule``: Orbit's own text
when the board carries one, else stated from its numeric rules), measures
(label, weight, status and sanitized definition), the not-scored count by
reason, ``scales_source`` and ``qualified``, and, per model, its
single-tier flag when Orbit sets one, its sanitized not-eligible reason,
its band (rank, ``rank_label`` and band size), score, raw score, p10-p90
interval, cost per task with its ratio and coverage, tasks by tier, landed
rate, per-measure contributions, crews with task counts and per-tier
scores. Rows whose model is ``model unknown`` and crews that are
attribution gaps are dropped and counted in ``dropped.rank``. The crew
``system`` is Orbit's attribution for system-run work, not a configured
crew, so it is dropped from rank crew lists and counted in
``dropped.rank`` the same way. A bare crew key (no ``@effort``) carries no
effort: its effort was not recorded, and it is shown as effort unknown.
Paired probabilities, z-scores, per-effort usage splits and the
unattributed crew list are not copied. Snapshots written before this key
existed have no ``rank.json``. Bundles written while the live board was
published, and those written before it, replay unchanged.

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

# Keep imports working for direct execution and loading this file by path.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _analytics_snapshot.common import (
    ABS_PATH,
    COMPLETION_DONE,
    DEFECT_LINEAGES,
    DEFECT_ORIGINS,
    DIFF_MEASURES,
    EXPERIMENT_OMITS,
    FAILURE_RATE_LABEL,
    FILE_URI,
    FRICTION_FAMILIES,
    FRICTION_PARTS,
    GAP_CREWS,
    GAP_MODELS,
    HOME_PATH,
    MIN_CONFIDENT_SAMPLE,
    MIN_SUPPORT_DEFAULT,
    OPTIONAL_KEYS,
    OUTCOME_COUNTS,
    PUBLIC_KEYS,
    RANK_EXECUTION,
    RANK_MEASURE_FIELDS,
    RANK_NON_CREW,
    RANK_RULES,
    RANK_SOURCE,
    RANK_TIERS,
    RELATIVE_PATH,
    ROLES,
    RUN_ID,
    SAFE_ID,
    SAFE_KEY,
    SAFE_LABEL,
    SAFE_TOKEN,
    SCHEMA_VERSION,
    SETTLED_UNTIL,
    TASK_ID,
    TIER_ORDER,
    TIMESTAMP,
    TOKEN_CELL,
    TURNS_CELL,
    TURNS_COVERAGE,
    WINDOW,
    WINDOWS_PATH,
    WORKSPACE_ID,
    _API_ROUTE,
    _PATH_SEGMENT,
    dump,
    empty_dropped,
    experiment_omitted,
    is_gap_actor,
    is_gap_crew,
    is_gap_model,
    is_number,
    is_rank_dropped_crew,
    number_list,
    numeric_map,
    project_usage,
    whole,
    window_of,
)
from _analytics_snapshot.redaction import (
    assert_no_gap_values,
    assert_unique_rows,
    forbidden_patterns,
    guard,
    host_names,
    sanitize,
    scan,
)
from _analytics_snapshot.api import (
    check_dashboard,
    http_json,
    orbit_json,
    orbit_version,
    scorecard_supports_until,
    workspace_id,
)
from _analytics_snapshot.scorecards import (
    assemble_scorecards,
    effort_sort_key,
    project_board,
    project_cells,
    project_effort,
    project_row,
    project_stats,
    project_string_list,
    project_terms,
    score_key,
)
from _analytics_snapshot.metrics import (
    duration_stats,
    project_actor,
    project_completion_counts,
    project_completions,
    project_defect_counts,
    project_defects,
    project_diff,
    project_diff_cell,
    project_diff_series,
    project_duration_series,
    project_durations,
    project_friction,
    project_friction_cell,
    project_number_cell,
    project_outcome_mix,
    project_token_series,
    project_tokens,
    project_turns,
    trend_window,
)
from _analytics_snapshot.reliability import (
    add_counts,
    failure_rate,
    project_counts,
    project_rate,
    project_reliability,
)
from _analytics_snapshot.experiments import (
    project_difference,
    project_experiment,
    project_experiments,
    project_interval_arm,
    project_metric,
)
from _analytics_snapshot.rank import (
    eligibility_rule,
    project_rank,
    project_rank_measure,
    project_rank_row,
    project_rank_row_measures,
    rank_text,
    single_tier,
)
from _analytics_snapshot.snapshot import (
    assemble_meta,
    collect,
    generated_now,
    load_bundle,
    project_all,
    replay,
    write_snapshot,
)
from _analytics_snapshot.self_test import (
    self_test,
)


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
