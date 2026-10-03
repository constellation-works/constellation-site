# Method: what stopped failed delivery runs

This describes Constellation Works building Orbit with Orbit, in Orbit's own repository.
It is not a benchmark and does not cover other operators. All times are UTC.

## Window and population

- Runs: leaf delivery runs (`task_pr_pipeline` and `task_local_pipeline`) created at or
  after `2026-07-06T00:00:00Z` and before `2026-10-01T00:00:00Z`, in a terminal state.
  July 6 is the earliest row in this run store. Runs still `running` are excluded (none
  in the window).
- Wrapper pipelines that dispatch delivery runs (`task_gate_pipeline`, `task_auto_pipeline`,
  workspace drains) are not counted, so no run is counted twice.
- Every run in the window carried exactly one task.
- Observation cutoff for regression reports and task outcomes: `2026-10-01T00:00:00Z`.
- Read on October 3, 2026; `aggregate.json` records the read time.

Failure rate is failed runs over all finished runs, including cancelled (43) and
interrupted (42) runs, which are not counted as failures.

## Classifying failed runs

Each failed run records the error of its failed step. `measure.py` matches that message
against ordered rules (`RULES`) and takes the first match. Every failed run in the window
had a message; none fell through unclassified. The last rule, `orbit_defect`, catches
anything not matched earlier. I read all 22 of its messages: 20 are defects or internal
contract errors in Orbit (store schema mismatches, unregistered or mis-wired pipeline
actions, task-state checks), and 2 are pipeline workers stopped by SIGTERM.

| Group | Category | What the message says |
|---|---|---|
| The agent stopped | `agent_declared_failure` | The agent's result declared `failed` (or `timeout`), or its handoff summary began `Outcome: failed` |
| Nothing to change | `no_change_to_ship` | The commit step found nothing to commit |
| A review rejected the change | `change_rejected_by_review` | The review gate returned `changes_required` or `incomplete`, or the independent review did not pass |
| The agent process | `missing_handoff_summary` | The agent finished without the execution summary required before delivery |
| The agent process | `agent_process_ended` | Error exit, wall-clock timeout, quota, or no valid result envelope |
| Other work | `checkout_changed_during_run` | A worktree integrity check found the checkout changed during the run |
| Other work | `conflict_or_stale_base` | Rebase or merge conflict, or the base branch moved or was ahead |
| The machine | `host_or_repository_setup` | Agent CLI not found, sandbox refused, merge method not allowed, network failure to GitHub |
| The machine | `orbit_defect` | Everything else: schema mismatches, unregistered actions, invalid internal inputs, stopped workers |

Order matters only where a message could match more than one rule; the first match wins.

## Reason codes

When an agent declares failure it may give a code of its own choosing (`error.code=` in
the message). `CODE_THEMES` in the script groups the 41 codes seen into five themes; a
code not listed would be reported as `other` (none were). Runs with no code are reported
as `no_code_given`. The grouping is a judgement; the codes and their counts are in the JSON
so you can regroup them.

## After failure and after success

- *Alert-sweep tasks*: a failed run counts as coming from an alert sweep when its task
  carries `code-scanning-sweep`, `ci-failure-sweep` or `dependabot-sweep`.
- *After first failure*: for each task with a failed run in the window, its first failed
  run, then the first `done` event at or after it and before the cutoff. "Via a later
  successful run" means a successful delivery run for the task started after that first
  failure. Other closures (by a person, an agent session or a no-change completion) are
  not distinguished, because their recorded actor is often missing.
- *Delivered*: a task with a successful delivery run in the window.
- *Regression report*: a task with a `regression_from` relation to the delivered task,
  created before the cutoff. Counted at most once per delivered task for the 186; the 246
  counts reports.
- *Reviewed run*: a run whose input set `review`. Review settings are per run, and nearly
  all reviewed runs were in September.
- *Filed by month*: tasks created in each month carrying `code-review`, `qa-sweep`,
  `full-review` or `security-review` (review findings), `ci-failure-sweep` (CI repairs),
  or a `regression_from` relation (regression reports).

## Limits

- One repository, one operator, three months, with Orbit changing underneath: pipeline
  steps, review settings, agents and models all changed during the quarter.
- Regression links exist only where someone filed and linked the fix. Linking was rare
  before August. The 186 is a floor and is right-censored for late-September deliveries.
- Classification depends on Orbit's error messages, which changed wording over the
  quarter. The rules match the wordings seen; a rerun on later data may need new rules.
- Merge conflicts and checkout changes are counted where the failing run noticed them, not
  attributed to whichever concurrent run caused them.
- This says nothing about which agents or models fail more. Crews were assigned by task
  complexity, so they did not get comparable work.

## Read procedure and reproduction

`measure.py` opens the run store and task index with SQLite `mode=ro`, `PRAGMA
query_only=ON` and a read transaction, and reads task bundle files (`task.yaml` status and
`events.jsonl`) for tasks with a failed run. It writes nothing and prints only aggregates.
Python 3.9 or later, no third-party packages:

```sh
python3 -B measure.py \
  --run-db "$RUN_DB" --task-index "$TASK_INDEX" --workspace "$WORKSPACE_BINDING" \
  --since 2026-07-06T00:00:00Z --until 2026-10-01T00:00:00Z \
  --cutoff 2026-10-01T00:00:00Z > aggregate.json
```

This reproduces the procedure, not access to the private records. Later edits to task
records can change a rerun's result.
