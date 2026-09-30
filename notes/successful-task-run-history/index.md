---
title: A successful run is not the whole task
summary: 20 of 431 completed tasks had earlier delivery runs. Those runs added 32% to that group's recorded pipeline time, but only 1.5% across the full cohort. Recovery also happened inside successful runs.
status: draft
image: card.png
author: Constellation Works
tags: operating data, recovery, measurement
---

**Twenty of 431 completed tasks had earlier delivery runs.** Counting those runs
adds 2.6 hours to the group's 8.2 hours of final successful runs: 32% more recorded
pipeline time. Across all 431 tasks, the increase is much smaller, 1.5%.

These are tasks Constellation Works completed while building
[Orbit](https://orbit-cli.com), a local-first runtime for coding agents, during
September 21–27, 2026. The records were read on September 30, with an observation
cutoff of September 30 at 00:00 UTC. This is one operator's work, not a benchmark.

The question is how much work disappears if we look only at a task's successful
delivery run. A *task* is the unit of requested work. A *delivery run* here is one
execution of Orbit's pull-request pipeline, which includes implementation, tool
calls, review gates and delivery steps. One task can have several runs.

## Count the earlier runs

For each task, we compared its last successful delivery run with all its recorded
delivery runs begun before it first reached `done`. Runs must have finished by
the observation cutoff and have a recorded duration. The final run's full
duration counts, including its last steps after the task changed state.

| Tasks | Count | Final successful runs | Earlier runs | All delivery runs |
|---|--:|--:|--:|--:|
| One delivery run | 411 | 165.3 h | 0.0 h | 165.3 h |
| More than one delivery run | 20 | 8.2 h | 2.6 h | 10.8 h |
| **All included tasks** | **431** | **173.5 h** | **2.6 h** | **176.1 h** |

These are **summed pipeline hours**, not hours elapsed on a clock. Runs can
overlap, and pipeline time includes waiting for tools and gates. It is not a
measure of model compute or hands-on human time.

The twenty tasks account for 48 runs: twenty final successes and 28 earlier runs.
The earlier runs ended as 8 `failed`, 11 `interrupted` and 9 `cancelled`.
Cancellations still consumed time, even when they were deliberate.

The 32% is a ratio of group totals: earlier-run time divided by final-run time
for the same twenty tasks. It is not the median task's increase. The median of
their individual increases is 8.4%, so the time is unevenly distributed. It also
does not mean that all work takes 32% longer: only 20 of 431 tasks, 4.6%, had
earlier delivery runs in this cohort.

Nor are all 28 earlier runs documented retries. Sixteen included run records
carry an explicit `retry_source_run_id`. We grouped by task identity so that a
freshly submitted run for the same task still counts, and call the result
*earlier runs* rather than treating every pair as a proven retry lineage.

## Recovery can fit inside a successful run

Twenty-eight of the 431 final successful runs, 6.5%, recorded a recovery call.
A `success` state therefore does not imply that the pipeline finished without
recovery.

Across all 459 included delivery runs, there are 36 recorded calls to the two
recovery activities checked here: 28 to `step_failure_recovery` and 8 to
`pr_conflict_recovery`. Their recorded durations sum to 2.1 hours. That time is
already inside the pipeline totals above; adding it again would double-count it.
Eight of the runs with recorded recovery were earlier runs; the other 28 were
final successes.

Invocation coverage has limits. Twenty-seven included runs have no matching
implementation invocation, including one final success. Missing telemetry is
not evidence that no agent worked. Only 168 of 432 matching implementation
invocations have a provider-reported cost, and none of the 36 recovery calls do.
These records support a pipeline-time account, not a complete dollar bill.

## What this measures

The store records 450 tasks first reaching `done` during the week. Nineteen have
no successful pull-request-pipeline run by the cutoff and are excluded, leaving
431. A task marked `done` or a run marked `success` is a workflow outcome; neither
establishes that the change is free of later regressions.

The included tasks are 88 low, 166 medium, 174 hard and 3 extra-hard, using the
complexity recorded when read. Models changed during the period. The comparison
uses each task's own final run as its baseline; it does not rank crews or models,
or estimate what the same work would have taken under a different policy.

We count only the PR pipeline. Its outer scheduling wrappers are excluded, and
each included run carries exactly one task. Planning, separate local pipelines,
human intervention, idle time between runs and later regression fixes are outside
these totals. One included run began before the cohort week; it belongs to a task
that completed within it.

The useful distinction is between *a successful run* and *the recorded work for
a completed task*. Earlier runs added little to this cohort's total, but mattered
for the tasks that had them. Recovery inside the final run is another part of
that record, even when the outcome is successful.

## Data and method

- [aggregate.json](aggregate.json): counts, durations, exclusions, model mix and
  coverage diagnostics. No task IDs, run IDs, workspace names, local paths,
  prompts or logs are included.
- [method.md](method.md): cohort rules, time definitions, attribution checks and
  limitations.
- [measure.py](measure.py): the read-only procedure that produced the aggregate.
  It requires access to an operator's own stores; the underlying private records
  are not published.
