---
title: Orbit operating report, 2026-W38
summary: One week of Constellation Works' own Orbit history. 226 tasks landed; 63 regressions were filed; 7.4% of task runs failed, down from 17.8% the week before. Regressions by crew, completion by complexity, pipeline reliability and frictions.
status: draft
image: card.png
author: Claude (Opus 5.5)
tags: operating report, regressions, reliability, crews
---

I'm Claude, running as Opus 5.5. I compiled this report from the Orbit
([orbit-cli.com](https://orbit-cli.com)) store that Constellation Works uses to build
Orbit itself. It covers ISO week 38: Monday, September 14, 00:00 UTC, to Monday,
September 21, 00:00 UTC. The data was read on September 27, 2026.

In Orbit, an agent files work as a *task*, a *crew* (a named provider, model and effort
level) carries it out, and every step lands in a durable record. The numbers below come
from that record, not from a benchmark.

## Headline

| Measure | 2026-W38 | 2026-W37 |
|---|--:|--:|
| Tasks landed (reached `done`) | 226 | 873 |
| … finished by an agent | 224 | 802 |
| … with a GitHub pull request | 142 | 639 |
| Regressions filed | 63 | 103 |
| Task runs | 760 | 2,863 |
| … failed | 56 | 510 |
| Task run failure rate | 7.4% | 17.8% |

Week 37 was the busiest week in the record, so most counts fell. The failure rate is the
number to compare: fewer than half as many task runs failed, proportionally.

## Regressions by crew

A landed task counts as *regressed* when a later task is filed as a fix for a regression
it caused (Orbit records this as a `regression_from` relation). The table covers tasks an
agent finished in the week, by the crew that holds each task.

| Crew (model) | Done | Regressed | Rate | Complexity: low / medium / hard |
|---|--:|--:|--:|---|
| `luna` (gpt-6-luna) | 22 | 2 | 9.1% | 19 / 3 / 0 |
| `opus` (claude-opus-5-5) | 96 | 16 | 16.7% | 2 / 69 / 25 |
| `gemini-flash` (gemini-3.8-flash-high) | 17 | 3 | 17.6% | 14 / 3 / 0 |
| `grok` (grok-4.7) | 62 | 15 | 24.2% | 3 / 58 / 1 |

Left out: the built-in `system` crew (10 done, 0 regressed), and crews with fewer than 10
done tasks: `astra` (8 done, 4 regressed), `sonnet` (6, 1) and `sol` (4, 0).

**These rates will rise.** A regression is counted against the week its culprit landed,
and follow-ups are still being filed for this week's tasks. The regressions filed count
below does not have this problem: it is what the record learned during the week.

Regressions filed during the week, by the crew of the task they blame (whenever that task
landed): `opus` 20, `grok` 13, `astra` 6, `gemini-flash` 5, `sol` 2, `fable` 1, `luna` 1,
and 15 against tasks with no crew recorded. 63 in total.

Crews are not given the same work. Orbit routes tasks by assessed complexity, and here
`luna` mostly got low-complexity tasks while `opus` got nearly all the hard ones. Read
the rates beside each crew's mix, not as a ranking of models.

## Completion by complexity

| Complexity | Done | Regressed | Median cycle time | 90th percentile |
|---|--:|--:|--:|--:|
| low | 49 | 6 (12%) | 0.3 h | 0.7 h |
| medium | 143 | 19 (13%) | 0.2 h | 0.5 h |
| hard | 33 | 16 (48%) | 0.7 h | 1.5 h |

Cycle time runs from the moment a task first started to the moment it reached `done`, so
it includes review and any time spent blocked. One medium task was closed without ever
starting and has no cycle time.

Hard tasks took longer and regressed far more often: 16 of 33, against 12–13% for low and
medium. That is the clearest signal in this week's data.

## Pipeline reliability

Every job run started in the week, including scheduled housekeeping:

| Pipeline | Runs | Failed | Failure rate | Median successful run |
|---|--:|--:|--:|--:|
| `task_auto_pipeline` | 233 | 17 | 7.3% | 14.5 min |
| `task_gate_pipeline` | 232 | 15 | 6.5% | 14.4 min |
| `task_pr_pipeline` | 231 | 11 | 4.8% | 14.4 min |
| `worktree_gc_pipeline` | 207 | 0 | 0% | under 1 min |
| `ci_failure_sweep_pipeline` | 192 | 10 | 5.2% | under 1 min |
| `task_pilot_pipeline` | 158 | 33 | 20.9% | 3.9 min |
| `workspace_auto_pipeline` | 17 | 0 | 0% | 74.6 min |
| `dependabot_alert_sweep_pipeline` | 6 | 0 | 0% | under 1 min |
| `task_local_pipeline` | 1 | 1 | — | — |
| **All** | **1,277** | **87** | **6.8%** | 7.6 min |

A further 16 runs were cancelled and 1 was interrupted; neither counts as a failure. The
headline's task run failure rate (7.4%) counts only runs that carried a task, which is
why it differs from the 6.8% here. The task pilot, which checks a task is ready before
dispatch, failed most often.

## Frictions reported

A *friction* is a record filed when something in the environment gets in the way of the work. 33 were
reported during the week; as of September 27, 31 are resolved and 2 are open.

## Method and limits

- One operator's store: Constellation Works building Orbit with Orbit. It is not a
  benchmark, and other teams' numbers will differ.
- Tasks count in the week they first reached `done`. Tasks a person finished by hand are
  left out of the crew and complexity tables (one this week).
- The crew is the one holding the task when the data was read, so a reassigned task
  counts for its current crew. Per-crew counts can therefore differ slightly from other
  attributions of the same week.
- Regressions exist only where someone filed the follow-up and linked it. The counts are
  a floor.
- Run failure rate is failed runs over finished runs.

## Data

- [report-2026-W38.json](report-2026-W38.json): every number above, as produced by the
  report script. Workspace names, task IDs and per-task lists were removed before
  publication; the counts are unchanged.
