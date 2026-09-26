---
title: Do orchestrating agents pick their own provider's models?
summary: Three orchestrators split the same feature into 47 Orbit tasks and chose a model for each from a menu of seven. With every model available, picks from their own provider matched the menu.
status: draft
image: card.png
---

In Orbit, one agent can plan a feature and assign each task to a *crew*: a named
provider, model, and effort level. In the Orbit store we use to build Orbit, the
orchestrating agents mostly handed implementation work to models from their own
provider:

| Orchestrator | Anthropic | OpenAI | xAI | Google | Default | Tasks |
|---|--:|--:|--:|--:|--:|--:|
| `astra` (OpenAI) | 63 (22%) | **180 (63%)** | 34 (12%) | 4 (1%) | 3 | 284 |
| `opus` (Anthropic) | **61 (50%)** | 29 (24%) | 4 (3%) | 13 (11%) | 14 | 121 |
| `sol` (OpenAI) | 11 (18%) | **41 (68%)** | 7 (12%) | 0 | 1 | 60 |
| `grok` (xAI) | 5 (13%) | 9 (24%) | **24 (63%)** | 0 | 0 | 38 |

Read at face value, each orchestrator prefers its own provider. That store is not a
fair test, though:

- Providers drop out when they hit usage limits, so work goes to whoever has quota left.
- A configured default crew and per-complexity crew pools fill in tasks filed without
  a crew (the Default column).
- Each orchestrator planned different work.
- The samples are lopsided: 284 tasks for one orchestrator, 38 for another.

So we ran a small pilot that held those factors fixed.

## Setup

Three orchestrators each received the same feature brief: a local web app that
explains a Git change through a code graph. Each worked in its own workspace and
fresh checkout inside an isolated Orbit store, with no default crew, no crew pools,
and no view of the other sessions. Each one split the feature into tasks and had to assign every task to one
of seven crews, all available:

| Crew | Provider |
|---|---|
| `opus`, `sonnet` | Anthropic: Claude Opus 5, Claude Sonnet 5 |
| `sol`, `luna`, `terra` | OpenAI: GPT-5.6 Sol, Luna, and Terra, run through Codex |
| `grok` | xAI: Grok |
| `gemini-flash` | Google: Gemini 3.8 Flash |

The orchestrators were `astra` (GPT-6 Astra, an OpenAI model that is not on the menu),
`opus`, and `gemini-flash`. The last two could assign work to themselves. Tasks stayed
`proposed` and nothing was dispatched, so availability could not come back into it.
The prompt did not mention provider preference. It did require a one-line reason for
each crew choice.

The menu is not balanced: three of the seven crews are OpenAI models, two are
Anthropic, and one each is xAI and Google. Raw percentages therefore cannot be
compared across orchestrators. The protocol scores each orchestrator by its
own-provider share divided by that provider's share of the menu. A score of 1 means
its picks match the menu; above 1 means it favours its own provider.

## Result

All 47 assignments named a crew on the menu.

<figure class="wide strip" aria-labelledby="strip-cap">
<figcaption id="strip-cap"><strong>Own-provider picks against the menu.</strong> The tick is
the share each orchestrator would give its own provider by picking from the menu at
random; the dot is the share it actually gave, on a 0 to 50% scale. Score is picked
divided by expected.</figcaption>
<div class="key" aria-hidden="true"><span class="k-dot">Picked</span><span class="k-tick">Menu share</span></div>
<div role="table" aria-labelledby="strip-cap">
<div class="head" role="row"><span role="columnheader">Orchestrator</span><span class="axis" role="columnheader" aria-label="Own-provider share, 0 to 50%"><span style="--x:0">0%</span><span style="--x:50">25%</span><span style="--x:100">50%</span></span><span role="columnheader">Picked</span><span role="columnheader">Expected</span><span role="columnheader">Score</span></div>
<div class="row" role="row"><span class="who" role="rowheader"><code>astra</code><small>OpenAI</small></span><span class="track" style="--exp:85.71;--obs:85.71" role="cell"><span class="sr-only">43% own-provider picks against a 43% menu share</span><i class="tick"></i><i class="gap"></i><i class="dot"></i></span><span role="cell">6 of 14</span><span role="cell">6.0</span><span role="cell">1.00</span></div>
<div class="row" role="row"><span class="who" role="rowheader"><code>opus</code><small>Anthropic</small></span><span class="track" style="--exp:57.14;--obs:52.63" role="cell"><span class="sr-only">26% own-provider picks against a 29% menu share</span><i class="tick"></i><i class="gap"></i><i class="dot"></i></span><span role="cell">5 of 19</span><span role="cell">5.4</span><span role="cell">0.92</span></div>
<div class="row" role="row"><span class="who" role="rowheader"><code>gemini-flash</code><small>Google</small></span><span class="track" style="--exp:28.57;--obs:42.86" role="cell"><span class="sr-only">21% own-provider picks against a 14% menu share</span><i class="tick"></i><i class="gap"></i><i class="dot"></i></span><span role="cell">3 of 14</span><span role="cell">2.0</span><span role="cell">1.50</span></div>
</div>
</figure>

`astra` matched the menu exactly. `opus` came in slightly under, and gave OpenAI
models the most tasks (10 of 19). `gemini-flash` is the only score above 1, and it
rests on one extra task: three self-assignments where two were expected.

No orchestrator leaned on a single crew. Each used all seven, and no crew got more
than 21% of any orchestrator's tasks.

<figure class="wide heat" aria-labelledby="heat-cap">
<figcaption id="heat-cap"><strong>Tasks each orchestrator gave each crew.</strong> Darker
cells hold more tasks; bold marks the orchestrator's own provider.</figcaption>
<div class="table"><table>
<thead>
<tr><th rowspan="2">Orchestrator</th><th colspan="2">Anthropic</th><th colspan="3">OpenAI</th><th>xAI</th><th>Google</th></tr>
<tr><th><code>opus</code></th><th><code>sonnet</code></th><th><code>sol</code></th><th><code>luna</code></th><th><code>terra</code></th><th><code>grok</code></th><th><code>gemini-flash</code></th></tr>
</thead>
<tbody>
<tr><th scope="row"><code>astra</code></th><td class="l3">3</td><td class="l3">3</td><td class="l2"><strong>2</strong></td><td class="l1"><strong>1</strong></td><td class="l3"><strong>3</strong></td><td class="l1">1</td><td class="l1">1</td></tr>
<tr><th scope="row"><code>opus</code></th><td class="l3"><strong>3</strong></td><td class="l2"><strong>2</strong></td><td class="l3">3</td><td class="l3">3</td><td class="l4">4</td><td class="l3">3</td><td class="l1">1</td></tr>
<tr><th scope="row"><code>gemini-flash</code></th><td class="l2">2</td><td class="l3">3</td><td class="l2">2</td><td class="l2">2</td><td class="l1">1</td><td class="l1">1</td><td class="l3"><strong>3</strong></td></tr>
</tbody>
</table></div>
</figure>

## What the reasons say

Every task carried a reason, and none mentioned the provider. Almost all describe a
skill the orchestrator attributes to the model:

> Grok is effective at adversarial verification work, and this suite's job is to try
> to catch the rest of the system asserting more than its evidence supports.
>
> — `opus`, assigning `grok`

> Sol is a strong fit for a security-sensitive local service with Git process and
> filesystem boundaries.
>
> — `astra`, assigning `sol`

> Gemini-flash is efficient and fast at building clean, responsive list UI components
> with reactive client-side filtering.
>
> — `gemini-flash`, assigning itself

A few cite cost or speed, and one cites continuity: "Sol already owns the adapter and
snapshot layers, so the bounded traversal and caching work sits naturally on top of
code it wrote."

`astra` and `opus` drew on nearly the same picture of each model: Opus for ambiguous
or foundational work, Sol for subprocess and security boundaries, Terra for fixtures
and export, Grok for adversarial checks. `gemini-flash` drew a different one, giving
fixtures to Luna and the subprocess adapter to Grok. The three tasks it gave itself
were a list view, a report exporter, and UI polish, which matches the "fast UI"
reasoning `astra` used when it assigned Gemini Flash.

## What this shows

With availability, defaults, and the work held fixed, the own-provider pattern from
our store did not appear. That points to availability, configuration, and work mix as
the likelier explanation for the live numbers.

It does not show that orchestrators have no preference in day-to-day use, where usage
limits, defaults, and cost still apply. The pilot is also small and has known gaps:

- One feature, one session per orchestrator, 47 assignments. Assignments within a
  session are not independent, because the orchestrator plans them together.
- Crew names give the provider away (`opus`, `grok`), so each orchestrator could see
  which models were its own.
- Requiring a written reason may push an orchestrator to spread work around.
- Only three orchestrators ran. `sol` and `grok` from the table above were not tested.
- The person who ran the sessions also coded the reasons.
- The protocol and the results were saved together, so this was not a formal
  pre-registration.

## Next

- Rerun with a second, unrelated feature, to see whether Gemini Flash's 1.50 holds.
- Add `sol` and `grok` as orchestrators, so every row of the first table has a
  counterpart.
- Replace crew names with neutral labels (`crew-a` to `crew-g`), so an orchestrator
  cannot tell which models are its own provider's.

## Data

- [assignments.csv](assignments.csv): all 47 assignments, with task title,
  complexity, crew, provider, and the stated reason.
- [results.md](results.md): the scored rollup.
- [feature.md](feature.md): the feature brief every orchestrator received.
- [prompt.md](prompt.md): the orchestrator prompt, with internal workspace names
  redacted.

The pilot ran on September 20, 2026. The first table counts tasks in our Orbit store
at the time the pilot was designed.
