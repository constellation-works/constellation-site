> Published with this note. Internal research-item ids are replaced with plain names (the pilot, the main run, the Opus 5 follow-up); nothing else is changed.

# the Opus 5 follow-up protocol (pre-registered)

Committed before any the Opus 5 follow-up session ran.

## Why

In the main run the `opus` orchestrator (Claude Opus 5.5) gave Anthropic's crews 74 of
its 100 tasks; the other four orchestrators gave them about a third. the pilot's
`opus` orchestrator was Claude Opus 5 and gave its own provider 5 of 19 tasks, on
one feature. the Opus 5 follow-up asks whether Opus 5 shows the same preference on the main run's five
features, or whether it arrived with Opus 5.5.

This protocol was written after the main run's Opus 5.5 sessions finished and their
Anthropic share was seen. The question is therefore prompted by that result;
the test below is fixed before the Opus 5 follow-up's own data exists.

## Design

Exactly the main run (features, seeds, prompt, menu, isolation, `setup.sh`, `run.sh`)
with one change: the `opus` orchestrator runs Claude Opus 5 (`claude-opus-5`,
Claude Code, effort high) instead of Opus 5.5. The prompt still binds the
orchestrator crew name `opus`. Five sessions, one per feature, run in parallel,
each with its own Orbit root (`~/.orbit-crew-pref-opus-5/<session>`), checkout
(`/var/tmp/crew-pref-opus-5/work/`) and throwaway `HOME`. 20 tasks per session,
100 in all.

Comparison data are the main run's sessions on the same features: `astra`,
`gemini-flash`, `grok` and `sol` (non-Anthropic), and `opus` (Opus 5.5).

## Outcomes

Valid tasks and shares are defined as in the main run.

### Primary

    d = mean over features of [ Opus 5's Anthropic share − mean Anthropic share of
        the main run's astra, gemini-flash, grok and sol on that feature ]

One-sided permutation test of d > 0: within each feature, the labels of the
five sessions (Opus 5 and the four) are shuffled; 100,000 draws, seed 16.
Supported if p < 0.05. This is the same comparison the main run makes for Opus 5.5.

### Secondary

1. **Opus 5 against Opus 5.5**: per-feature difference in Anthropic share, the
   mean difference, and an exact two-sided sign-flip test over the five
   features. With five features the smallest possible p is 2/32 ≈ 0.06, so this
   comparison is reported as an effect size and cannot reach 0.05 on its own.
2. Own-crew (`opus`) version of the primary statistic.
3. Lift against the menu, as the pilot.
4. Crew counts for Opus 5 beside Opus 5.5.

Reasons are published; they are not coded for the Opus 5 follow-up.

### What would change our mind

- d near the main run's Opus 5.5 value (+0.37 before the main run's grok sessions finish) and
  p < 0.05: the preference is not new in Opus 5.5; the pilot missed it because its
  one feature, or its one session, was unrepresentative.
- d near 0: Opus 5 did not favour its provider on these features; the
  difference lies with the newer model.

## Running

1. `./setup.sh` (done before this commit: five roots, `sessions.tsv`).
2. `./run.sh` runs the five sessions in parallel.
3. A session that exits non-zero, times out or files fewer than 10 valid tasks
   is rerun once from a fresh root and checkout.
4. `score.py collect`, then `score.py analyze` once the main run's sessions are all in.

## Limitations accepted in advance

- The question was chosen after seeing the main run's Opus 5.5 result.
- the Opus 5 follow-up runs about an hour after the main run on the same host and account; the
  comparison sessions are the main run's, not rerun alongside.
- As the main run: crew names reveal the provider; the operator is an Anthropic model.
