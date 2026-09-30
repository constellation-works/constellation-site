# Method: completed tasks and delivery-run time

This procedure describes Constellation Works building Orbit. It does not measure
product adoption or other operators' workloads. All timestamps are UTC.

## Window and coverage

- Task cohort: first event with `to_status: done` at or after
  `2026-09-21T00:00:00Z` and before `2026-09-28T00:00:00Z`.
- Observation cutoff, exclusive: `2026-09-30T00:00:00Z`.
- Read: September 30, 2026, 04:06:51–04:06:52 UTC; the precise timestamps are in
  `aggregate.json`.
- Reviewed Orbit source revision:
  [`08c6556d9dde350b505e880290be484f2fb09519`](https://github.com/constellation-works/orbit/tree/08c6556d9dde350b505e880290be484f2fb09519).
  This identifies the source inspected, not every binary that wrote historical rows.
- 3,294 registered task bundles were examined for this workspace. All event files
  were readable. There were 450 first-done tasks in the window: 436 ordinary
  status-change events, 10 forced events, 3 review-approval events and 1 landing
  event. All these event types are eligible; none implies correctness.
- Nineteen tasks lacked a successful PR-pipeline run completed by the cutoff and
  were excluded. There were no further exclusions for shared runs or unusable
  durations. The remaining 431 tasks have 459 included runs.

The run-store row count in the JSON describes the database at read time across
workspaces. It is a coverage diagnostic, not the task denominator.

## Read procedure

`measure.py` uses SQLite URI `mode=ro`, `PRAGMA query_only=ON` and an explicit read
transaction. The task index is attached read-only; both database snapshots are
established before reading task bundles. Nothing is written to the stores, and
the script does not invoke Orbit, run a migration or query a running service.

Task event files and the scalar complexity field are read from the registered
bundle paths. The script checks size and modification time before and after
reading and again at the end, failing if a file changes. Bundle files do not
participate in the SQLite transaction. These checks detect ordinary concurrent
edits, but do not create an atomic snapshot across the database and files.
The cutoff freezes eligible timestamps, not a historical backup: later repairs
to old rows or events can change a rerun's result.

Descriptions, acceptance criteria, plans, comments, prompt text, tool payloads,
raw logs and account information are not exported. Task, run and workspace
identities and operator paths remain private. The published output contains
aggregates only, including model names recorded on the final runs.

## Cohort and run selection

1. Read all task bindings for the chosen workspace. Use the earliest recorded
   `done` transition, regardless of the current status or `updated_at`.
2. For cohort tasks, select runs of `task_pr_pipeline` in that same workspace,
   with input `task_ids` containing the task and a start no later than first done.
3. Require one distinct task per run. Exclude a task if its history includes a
   shared run; do not divide its time arbitrarily among tasks.
4. Require terminal state (`success`, `failed`, `timeout`, `interrupted`,
   `cancelled` or `skipped`), finish before the cutoff, and nonnegative recorded
   `duration_ms`. Exclude a task with an associated incomplete or unusable run.
5. Require at least one eligible successful run. The final successful baseline
   is the one with the latest start time, with run identity as a deterministic
   tie-breaker. Each run is counted once.
6. Sum recorded durations for all eligible delivery runs. Subtract the final
   successful run's duration to obtain earlier-run time.

In this sample, every included task has exactly one successful delivery run, so
the remaining 28 runs are all non-successful. States are reported separately;
no failure-rate series is calculated or joined to the earlier weekly report.
Run duration is used as stored, not recomputed from invocation durations.

The final run often performs a task's `done` transition before it finalizes:
399 of 431 final runs finished after that transition. Their full recorded run
durations are included, provided they finished before the cutoff. The figures
therefore measure completed delivery runs, not time cut off at the exact `done`
event. Runs started after first done are excluded, as are later regression tasks.

Only the leaf PR pipeline counts. `task_auto_pipeline`, `task_gate_pipeline` and
workspace scheduling wrappers are excluded rather than summed alongside their
child runs. Other delivery modes and planning work are outside scope.

## Retry and invocation attribution

Task grouping covers explicit resumes and fresh submissions of the same task.
It does not infer a retry edge from temporal proximity. Sixteen included runs
carry `retry_source_run_id`; eight distinct referenced source identities are
also among the selected leaf runs. Source references may point outside this
selection, including wrapper runs. The twenty tasks with multiple delivery runs
are not presented as twenty proven retry chains.

Invocation rows are counted once by their primary key. A run ID alone is
insufficient: 17 selected run IDs also appear in another workspace. The procedure
requires the invocation's distinct linked-task set to equal the selected run's
singleton task. Twelve candidate invocation rows fail that check and are excluded.
This also prevents copying the full duration of a shared invocation onto each task.

The two recovery activities are `step_failure_recovery` and
`pr_conflict_recovery`, checked against the existing PR-pipeline job definition,
where both are declared recovery hooks. No other activity is inferred to be
recovery from its duration, outcome or name. Calls are included only when both
their leaf-run identity and exact task link match and their timestamp precedes
the cutoff. Invocation timestamps record persistence time, rather than the
activity's start time. The selected invocation timestamps range from September 20 at
23:41:14 UTC through September 27 at 23:53:24 UTC.

Twenty-seven selected runs have no matched `implement_one` invocation; one is a
final success. Recovery-call incidence is observed telemetry, not a claim of
complete instrumentation. The 36 recovery-call durations are nested within run
time and must never be added to the 176.1 pipeline hours. There is no dollar
estimate: only 168 of 432 matched implementation invocations report provider
cost, while 0 of 36 recovery invocations do. Missing cost is not zero cost.

Relevant source contracts:

- [Run and retry contract](https://github.com/constellation-works/orbit/blob/08c6556d9dde350b505e880290be484f2fb09519/crates/orbit-store/src/contracts/job_run.rs).
- [Invocation insertion and task links](https://github.com/constellation-works/orbit/blob/08c6556d9dde350b505e880290be484f2fb09519/crates/orbit-store/src/driver/sqlite/invocation_store/records/mod.rs).
- [Invocation persistence](https://github.com/constellation-works/orbit/blob/08c6556d9dde350b505e880290be484f2fb09519/crates/orbit-core/src/adapter/engine_host/runtime_host/invocation.rs).
- [Telemetry duration and provider-cost fields](https://github.com/constellation-works/orbit/blob/08c6556d9dde350b505e880290be484f2fb09519/crates/orbit-types/src/telemetry/invocation.rs).

## Units, ratios and interpretation

- Convert milliseconds to hours by dividing by 3,600,000.
- Group increase = sum of earlier-run duration / sum of final-run duration.
- Paired median increase = median of each task's earlier/final duration ratio.
- Multiple-run incidence = 20 / 431; recorded final-run recovery incidence = 28 / 431.
- Hours round to one decimal; percentages round to one decimal, or 32% in the
  article's opening. The JSON retains integer milliseconds and unrounded ratios.

The group increase is 31.9% for the twenty tasks with earlier runs and 1.5% for
all 431 tasks. The median paired increase for the twenty is 8.4%. These are
different summaries of the same records; none is a counterfactual estimate of
what would have happened without recovery.

Pipeline duration includes tools, gates and any waiting inside a run. Summing
overlapping runs does not measure elapsed wall time or agent compute time.
Complexity is current metadata when read; model identity is from the final run.
The work mix is 88 low, 166 medium, 174 hard and 3 extra-hard tasks. The JSON lists
the model mix, which includes upgrades during the period. No between-model,
between-crew or between-week comparison is made.

Selection on completed tasks omits still-open work and unsuccessful work with
no later successful PR run. Idle intervals, human work, planning, other pipelines
and subsequent fixes are also absent. The result is a scoped account of recorded
delivery time, not the lifetime cost of all agent work or a quality benchmark.

## Reproduction

With Python 3.9 or later, set `RUN_DB`, `TASK_INDEX` and `WORKSPACE_BINDING` to
the operator's own store paths and SQL workspace binding. No third-party Python
dependencies are required. Run where those stores and their registered task
bundle paths are readable:

```sh
python3 -B measure.py \
  --run-db "$RUN_DB" \
  --task-index "$TASK_INDEX" \
  --workspace "$WORKSPACE_BINDING" \
  --since 2026-09-21T00:00:00Z \
  --until 2026-09-28T00:00:00Z \
  --cutoff 2026-09-30T00:00:00Z \
  --source-revision 08c6556d9dde350b505e880290be484f2fb09519 \
  > aggregate.json
```

This recreates the procedure, not access to private data. Read timestamps and
database coverage counts can differ on a later run; historical corrections can
also change the cohort. Do not place raw records beside a note: the site build
copies every sibling file into the rendered note.
