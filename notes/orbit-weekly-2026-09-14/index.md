---
title: Orbit weekly report: September 14–20, 2026
summary: 226 tasks landed, 63 regressions were filed, 7.4% of task runs failed (17.8% the week before) and 33 frictions were reported. Regressions by crew, completion and implementation time by complexity, and pipeline reliability from Constellation Works' own Orbit store.
status: published
date: 2026-09-27
image: card.png
author: Constellation Works
tags: weekly report, regressions, reliability, crews
---

This is the weekly operating report from the Orbit ([orbit-cli.com](https://orbit-cli.com))
store that Constellation Works uses to build Orbit itself. It covers Monday, September 14, to Sunday, September 20, 2026
(ISO week 2026-W38, Monday to Monday, UTC). The data was read on September 27, 2026.

In Orbit, an agent files work as a *task*, a *crew* (a named provider, model and effort
level) carries it out, and every step lands in a durable record. The numbers below come
from that record, not from a benchmark.

## This week

- The task run failure rate fell to 7.4%, from 17.8% the week before.
- Hard tasks regressed most often: 16 of 33, against 12–13% for low and medium.
- Of the pipelines with 5 or more runs, `task_pilot_pipeline` failed most often: 33 of 158 runs (20.9%).

## Headline

| Measure | Sep 14–20 | Sep 7–13 |
|---|--:|--:|
| Tasks landed (reached `done`) | 226 | 873 |
| … finished by an agent | 224 | 802 |
| … with a GitHub pull request | 142 | 639 |
| Regressions filed | 63 | 103 |
| Task runs | 760 | 2,863 |
| … failed | 56 | 510 |
| Task run failure rate | 7.4% | 17.8% |

## Regressions by crew

A landed task counts as *regressed* when a later task is filed as a fix for a regression
it caused (Orbit records this as a `regression_from` relation). The table covers tasks an
agent finished in the week, by the crew that holds each task, with each crew's mix of
assessed complexity.

| Crew (model; effort) | Done | Regressed | Rate | Complexity: low / medium / hard / other |
|---|--:|--:|--:|---|
| `luna` (gpt-5.6-luna; xhigh effort) | 22 | 2 | 9.1% | 19 / 3 / 0 / 0 |
| `opus` (claude-opus-5; high effort) | 96 | 16 | 16.7% | 2 / 69 / 25 / 0 |
| `gemini-flash` (gemini-3.8-flash-high; high effort) | 17 | 3 | 17.6% | 14 / 3 / 0 / 0 |
| `grok` (grok-4.6; high effort) | 62 | 15 | 24.2% | 3 / 58 / 1 / 0 |

Left out of the table: the `system` crew (10 done, 0 regressed), and crews with fewer than 10 done tasks: `astra` (8 done, 4 regressed), `sonnet` (6 done, 1 regressed) and `sol` (4 done, 0 regressed).

These rates will rise: a regression counts against the week its culprit landed, and
follow-ups for this week's tasks are still being filed. Regressions filed during the week,
by the crew of the task they blame (whenever that task landed): `opus` 20, `grok` 13, `astra` 6, `gemini-flash` 5, `sol` 2, `fable` 1 and `luna` 1, and 15 against tasks with no crew recorded; 63 in total.

Orbit routes tasks to crews by assessed complexity, so crews are not given the same work.
Read each rate beside its crew's mix, not as a ranking of models.

## Completion by complexity

| Complexity | Done | Regressed | Median cycle time | 90th percentile |
|---|--:|--:|--:|--:|
| low | 49 | 6 (12%) | 0.3 h | 0.7 h |
| medium | 143 | 19 (13%) | 0.2 h | 0.5 h |
| hard | 33 | 16 (48%) | 0.7 h | 1.5 h |

Cycle time runs from the moment a task first started to the moment it reached `done`, so
it includes review and any time spent blocked. 1 task was closed without ever starting and has no cycle time.

## Implementation time

Average time of the agent implementation step (`implement_one`), by crew and task
complexity: mean minutes, with the number of steps in brackets. Every attempt counts, so a
retried task counts more than once, and only successful steps are timed.

| Crew (model; effort) | Low | Medium | Hard |
|---|--:|--:|--:|
| `opus` (claude-opus-5; high effort) | 6.9 min (2) | 12.6 min (67) | 39.6 min (25) |
| `grok` (grok-4.6; high effort) | 11.8 min (3) | 17.1 min (56) | 21.2 min (1) |
| `luna` (gpt-5.6-luna; xhigh effort) | 13.3 min (19) | 16.4 min (3) | 52.9 min (1) |
| `gemini-flash` (gemini-3.8-flash-high; high effort) | 13.9 min (14) | 20.9 min (3) | — |
| `sonnet` (claude-sonnet-5; high effort) | 9.4 min (3) | 11.9 min (3) | — |
| `astra` (gpt-6-astra; medium effort) | — | — | 35.1 min (5) |
| `sol` (gpt-5.6-sol; high effort) | — | 15.9 min (2) | — |

214 successful steps in total. Not shown: 7 by the `system` crew. Medians are in the data file.

## Pipeline reliability

Every job run started in the week, including scheduled housekeeping:

| Pipeline | Runs | Failed | Failure rate | Median successful run |
|---|--:|--:|--:|--:|
| `task_auto_pipeline` | 233 | 17 | 7.3% | 14.5 min |
| `task_gate_pipeline` | 232 | 15 | 6.5% | 14.4 min |
| `task_pr_pipeline` | 231 | 11 | 4.8% | 14.4 min |
| `worktree_gc_pipeline` | 207 | 0 | 0.0% | under 1 min |
| `ci_failure_sweep_pipeline` | 192 | 10 | 5.2% | under 1 min |
| `task_pilot_pipeline` | 158 | 33 | 20.9% | 3.9 min |
| `workspace_auto_pipeline` | 17 | 0 | 0.0% | 74.6 min |
| `dependabot_alert_sweep_pipeline` | 6 | 0 | 0.0% | under 1 min |
| `task_local_pipeline` | 1 | 1 | — | — |
| **All** | **1,277** | **87** | **6.8%** | 7.6 min |

Also: 16 cancelled and 1 interrupted; none of these count as failures. Failure rates are left blank for pipelines with fewer than 5 runs. The headline's task run failure rate counts only runs that carried a
task, so it differs from the total here.

## Frictions reported

A *friction* is a record filed when something in the environment gets in the way of the
work. 33 were reported during the week; as of September 27, 2026, 31 are resolved and 2 are open.

## Method and limits

- One operator's store: Constellation Works building Orbit with Orbit. It is not a
  benchmark, and other teams' numbers will differ.
- Tasks count in the week they first reached `done`. Tasks a person finished by hand are
  left out of the crew and complexity tables (1 this week).
- The crew is the one holding the task when the data was read, so a reassigned task counts
  for its current crew. Models are the ones the week's runs recorded for each crew; crews
  are upgraded over time, so the same crew name can mean a different model in another week.
  Effort is the level set for each crew that week.
- The crew table leaves out the built-in `system` crew and crews with fewer than 10
  done tasks.
- Regressions exist only where someone filed the follow-up and linked it, so the counts
  are a floor.
- Run failure rate is failed runs over finished runs; cancelled and interrupted runs are
  not failures.

## Data

- [report-2026-W38.json](report-2026-W38.json): every number above except the headline, as produced by the
  report script. Workspace names, task IDs and per-task lists were removed before
  publication; the counts are unchanged.
