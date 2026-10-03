---
title: Measure the whole coding task
summary: Count every recorded attempt when measuring a completed coding task. Earlier runs added 1.5% to our cohort's pipeline time, with the increase concentrated in 20 of 431 tasks.
status: published
date: 2026-10-02
image: card.png
author: Constellation Works
tags: operating data, recovery, measurement
---

**When you measure how much work a coding agent task took, include every recorded
attempt for that task.** The final successful run leaves out time spent on
earlier attempts.

A hypothetical example: a failed attempt takes 10 pipeline minutes, then a
successful attempt takes 20. The completed task took 30 recorded pipeline
minutes. Reporting only the success would show 20. This illustrates the counting
rule; it is not an observation from our data.

## What the records showed

Across **431 completed tasks**, earlier delivery runs added **1.5%** to recorded
pipeline time: 173.5 hours for final successful runs became 176.1 hours when
earlier runs were included. The overall difference was small.

It was concentrated in **20 of those 431 tasks**. Their earlier runs added
2.6 hours to 8.2 hours of final successful runs, bringing their total to
10.8 hours: **32% more** for that subset. This is a ratio of group totals,
not a typical task's increase; the median individual increase within the subset
was 8.4%. The other 411 tasks had one delivery run each.

The 28 earlier runs ended as 8 failed, 11 interrupted and 9 cancelled. A
deliberate cancellation still belongs in the task's recorded time.

Recovery can also happen inside a successful run. Twenty-eight final successes
(6.5%) recorded a recovery call. Across all included runs, the 36 recorded
recovery calls took 2.1 hours, already included in the pipeline totals. Adding
that time again would double-count it.

## Apply this to your own reports

- Group runs by stable task identity, including fresh submissions for the same
  task, rather than relying only on explicit retry links.
- Include earlier failed, interrupted and cancelled attempts, with a stated
  cutoff and rules for incomplete records.
- Count each pipeline run once. Exclude outer scheduling wrappers and do not
  add nested recovery time again.
- Report the overall total alongside the subset with earlier attempts. A large
  increase for that subset can coexist with a small overall difference.
- Keep summed pipeline duration separate from elapsed wall time, human time,
  model compute and dollars. Runs can overlap; their duration includes tools,
  review gates and waiting.

Orbit records delivery runs against task identities and links agent invocations
to tasks. That let us collect earlier runs even when they were fresh submissions
rather than explicit retries, and identify recovery within a run. If you want
to inspect or try that approach, start with the
[Orbit repository](https://github.com/constellation-works/orbit).

## Scope of the evidence

These records cover one operator at Constellation Works building Orbit, for
tasks first reaching `done` during September 21–27, 2026. Of 450 such tasks,
19 had no successful PR-pipeline run by the September 30, 2026, 00:00 UTC
cutoff and were excluded, leaving 431. We count eligible PR-pipeline runs begun
before first completion and finished before the cutoff, including the final
run's full duration.

This completed-task selection excludes still-open work and unsuccessful work
without a later success. Planning, human intervention, gaps between attempts,
other pipelines and later fixes are outside the totals. Telemetry and provider
cost coverage are incomplete. These figures do not establish change quality,
benchmark models or crews, or support a dollar estimate or an adoption claim.

The [aggregate](aggregate.json), [detailed method](method.md) and
[read-only measurement script](measure.py) provide the counts, selection rules
and coverage limits. The underlying private records are not published.
