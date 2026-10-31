# Method: medium-tier cheap crews experiment

This describes one Orbit experiment, `exp-4e3e0399` (`medium-tier-cheap-crews`), in the
workspace for Orbit's own repository. It is not a benchmark and does not cover other
operators. All times are UTC.

## Design

- Started 2026-10-28T05:35Z, concluded 2026-10-31T18:35Z with no arm chosen. Mode `live`:
  arm overlays applied to real deliveries.
- Population: tasks admitted for delivery at complexity `medium`, excluding the tags
  `breaking-change`, `no-diff-expected`, `release` and `security`. One cheap-pool task's
  complexity was later recorded as `hard`. The complexity-stratified differences drop
  that cell, because control has no hard task to compare with.
- Assignment: at delivery admission, by a salted hash of the task id, weights 1:1. A task
  keeps its arm across retries.
- Arms:
  - `control`: no overlay. The crew comes from the workspace's live `medium_complexity_crews`
    pool, which changed during the run (see below).
  - `cheap-pool`: crew pool overlay of `luna`, `haiku` and `muse-spark` at equal weight.
- Primary metric `cost_usd`. Guardrails: `delivery_done_rate` −5 pt, `escaped_regressions`
  +3 pt, `review_repairs` +0.5, `final_recoveries` +0.2. Minimum sample 60 per arm,
  maximum 21 days. The verdict was read when every arm passed its minimum sample.

## Readout

Orbit computes the readout on read from its own records. `readout.json` is the copy stored
on the conclusion event, read at 2026-10-31T18:35:14Z.

- Intention-to-treat by task: a task counts in its assigned arm whichever crew ran it.
- Means and medians carry 95% bootstrap intervals with a fixed seed. Rates use Wilson
  intervals. Differences from control are post-stratified by complexity.
- Enrollment: 230 analysed. 10 excluded because a crew was set explicitly on the task,
  2 excluded as interactive. None forced.
- Sample ratio: chi-square against the weights, p = 0.596.

## Cost

`cost_usd` per task sums its implement invocations. A provider-reported dollar figure is
used when present. Otherwise the cost is derived from `model_prices.yaml`, Orbit's
versioned price configuration, and marked estimated. If any invocation of a task has no
price, the whole task is unmeasured: no partial sums. Coverage at conclusion:

| Arm | Reported | Estimated | Unmeasured |
|---|--:|--:|--:|
| control | 13 | 56 | 41 |
| cheap-pool | 19 | 47 | 51 |

Muse models had no price row, so every Muse task is unmeasured. The pricing fix landed
on October 29, during the run, and the readout recomputes every task with it. The
day-one figures in the note ($0.21 control, $0.49 cheap pool) predate it.

## Control drift and crew mismatches

Control read the live pool, which moved from `muse-wonder, sol` to
`muse-wonder, terra, grok` during the run. The readout's crew mix records what actually
ran. For some control tasks the admission pool wasn't recorded, so a mismatch could not
be confirmed either way. Six cheap-pool tasks ran a crew outside the overlay pool; they
stay in the cheap-pool arm.

## Open outcomes

`escaped_regressions` is measured 14 days after a task lands. At conclusion, 224 landed
tasks were inside that window and 3 enrolled tasks were still open. This guardrail is
unknown until the window closes, around November 14.
