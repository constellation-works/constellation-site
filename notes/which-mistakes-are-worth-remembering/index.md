---
title: Which mistakes are worth remembering?
summary: A live crew-memory trial found no clear benefit. A break-even rule suggests which mistakes are worth remembering and when a reminder should surface.
status: published
date: 2026-11-23
author: Daniel Kim
tags: operating data, crew memory, experiments
---

Crew memory started with a ranking discussion. I was sharing the weekly results with Grok, Sol, Muse-Wonder, and Opus when I realized that the rankings could show a crew where it fell short, but didn’t give it a way to learn from those mistakes across tasks. I thought giving each crew a memory of its own would help it do better on the next job.

The result surprised me. In a [419-task live trial](https://github.com/constellation-works/orbit/blob/v0.53.0/docs/design/crew-memory/4_decisions.md#keep-the-machinery-dormant-after-the-no-difference-readout), first-pass acceptance was 66.9% without memory and 59.0% with it, among tasks with a measured verdict. The memory arm used an estimated 1.07 million more implementation tokens per task and cost an estimated $0.38 more per task. The acceptance and cost intervals included zero. So we didn’t establish that memory hurt, but we also didn’t see a benefit that justified keeping it on. We closed the trial without a winner and kept the machinery for future experiments.

Think of a list of every word you’ve ever misspelled. A short list of words you keep getting wrong might improve your spelling. Making yourself reread the whole list every time you write would mostly make writing slower. The same goes for agents: a past mistake is worth saving when it’s likely to recur, or when repeating it would be costly. Even then, it helps to show the reminder only when it applies.

**A break-even rule:** Keep a memory when the expected loss it prevents exceeds what it costs to write, maintain, retrieve, and read.

> Expected value = future tasks × chance the issue applies × chance the reminder reaches the agent when it applies × reduction in mistake probability when shown × cost of the mistake − total memory cost.

Count the cost of showing the memory on irrelevant tasks too. That’s where an always-on memory pack can lose even if a few entries are useful. The next version I’d test would save a short instruction with a clear trigger, then measure whether it actually prevents the same mistake from happening again.
