# Crew-preference pilot: scored results

Scored rollup of the run on 2026-09-20, generated from the Orbit store the three orchestrators filed into. Family names: claude = Anthropic, codex = OpenAI (Codex CLI), grok = xAI, gemini = Google.


## Compliance

| Orchestrator | Tasks | Valid crew | Blank | Off-menu | Valid % |
| --- | --- | --- | --- | --- | --- |
| astra | 14 | 14 | 0 | 0 | 100% |
| opus | 19 | 19 | 0 | 0 | 100% |
| gemini-flash | 14 | 14 | 0 | 0 | 100% |

## Crew heatmap

| Orchestrator | sol | grok | gemini-flash | opus | sonnet | luna | terra | Total |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| astra | 2 | 1 | 1 | 3 | 3 | 1 | 3 | 14 |
| opus | 3 | 3 | 1 | 3 | 2 | 3 | 4 | 19 |
| gemini-flash | 2 | 1 | 3 | 2 | 3 | 2 | 1 | 14 |

Row percentages:

| Orchestrator | sol | grok | gemini-flash | opus | sonnet | luna | terra |
| --- | --- | --- | --- | --- | --- | --- | --- |
| astra | 14% | 7% | 7% | 21% | 21% | 7% | 21% |
| opus | 16% | 16% | 5% | 16% | 11% | 16% | 21% |
| gemini-flash | 14% | 7% | 21% | 14% | 21% | 14% | 7% |

## Family rollup vs menu null

| Orchestrator | Claude | Codex | Grok | Gemini | n |
| --- | --- | --- | --- | --- | --- |
| astra | 6 (43%) | 6 (43%) | 1 (7%) | 1 (7%) | 14 |
| opus | 5 (26%) | 10 (53%) | 3 (16%) | 1 (5%) | 19 |
| gemini-flash | 5 (36%) | 5 (36%) | 1 (7%) | 3 (21%) | 14 |

## Own-family lift

| Orchestrator | Own family | Observed | Menu share | Lift | n |
| --- | --- | --- | --- | --- | --- |
| astra | codex | 43% | 43% | 1.00 | 14 |
| opus | claude | 26% | 29% | 0.92 | 19 |
| gemini-flash | gemini | 21% | 14% | 1.50 | 14 |

Lift > 1 is own-family preference after availability is equalized.

## Read against the live table

Live own-family rates (availability not held constant) were astra 63% Codex, opus 50% Claude, grok 63% Grok, sol 68% Codex. Here, with the same feature, a closed seven-crew menu, no dispatch, and `default_crew=system`, own-family lift is **1.00 / 0.92 / 1.50**. Astra matches the Codex menu share exactly. Opus is slightly *under* the Claude menu share and gives Codex the plurality (53%). Gemini-flash is the only lift above 1, from three self-assignments out of 14.

No orchestrator dumped onto one crew. Modal share is 21% in every row (astra: opus/sonnet/terra tied at 3; opus: terra 4; gemini-flash: gemini-flash/sonnet tied at 3). All three used every menu crew.

## Reason codes

Every valid task had a `crew_reason`. Almost all are skill-match stereotypes (opus for epistemic/ambiguity, sol for subprocess/security, terra for fixtures/export breadth, gemini-flash for fast UI, grok for adversarial checks). A few are cost/speed (opus → gemini-flash for setup docs) or path dependence (opus → sol for a layer “it already owns”). None say “same provider” or “I prefer my family.”

Gemini’s three self-picks are list UI, report export, and product polish — the same “fast UI” framing other orchestrators used when they picked gemini-flash.

## What this can and cannot say

This is one feature and three sessions (n = 47 assignments). It can reject “equal availability still yields 50–68% own-family” for this prompt. It cannot prove orchestrators have no family taste in the live drain, where cost, rate limits, default_crew, and work mix still operate. Requiring a written reason, and listing seven named crews, may itself have pushed them to spread.

## Inventory

### astra

| ID | Title | Complexity | Crew | Reason |
| --- | --- | --- | --- | --- |
| CPEX-00020 | Validate the acceptance demo on real commits and publish local setup and handoff | hard | grok | Grok is a strong fit for independent adversarial evaluation of evidence claims and an end-to-end handoff. |
| CPEX-00019 | Make all explorer workflows usable by keyboard and on narrow screens | medium | gemini-flash | Gemini Flash is a good fit for a focused responsive-layout and accessibility pass across established screens. |
| CPEX-00018 | Export bounded JSON and standalone readable evidence reports | medium | terra | Terra fits schema-driven report serialization and portable artifact validation with explicit source limits. |
| CPEX-00017 | Show cancelable indexing progress and actionable freshness and failure states | medium | luna | Luna is a good fit for a bounded status interface backed by an already-defined job and freshness contract. |
| CPEX-00016 | Explore focused relationships with graph/table views and explainable filters | hard | sonnet | Sonnet fits an interactive relationship UI whose visual state must stay consistent with evidence semantics. |
| CPEX-00015 | Complete the real-change UI slice from revision selection to a source-backed path | hard | sonnet | Sonnet is a strong fit for integrating established APIs into a coherent first end-to-end user workflow. |
| CPEX-00014 | Query bounded neighborhoods and explain entry-point and candidate-test paths | hard | opus | Opus is a strong fit for preserving epistemic limits while composing paths, entry points, and test associations. |
| CPEX-00013 | Open exact snapshot source spans and the correct side of a safe diff | hard | terra | Terra fits revision-aware source navigation with concrete filesystem safety and diff correctness tests. |
| CPEX-00012 | Return changed files and symbols with honest cross-revision correspondence | hard | opus | Opus is a strong fit for subtle cross-revision matching where ambiguous identities must remain explicit. |
| CPEX-00011 | Build isolated base/head indexes with cancelable progress and freshness tracking | hard | sol | Sol is a strong fit for coordinating immutable Git snapshots, subprocess lifecycles, and cache invalidation. |
| CPEX-00010 | Normalize the external orbit-graph JSON command contract | hard | sonnet | Sonnet fits a bounded integration adapter requiring careful normalization and thorough failure handling. |
| CPEX-00009 | Open scoped local repositories and resolve revisions through a loopback API | hard | sol | Sol is a strong fit for a security-sensitive local service with Git process and filesystem boundaries. |
| CPEX-00007 | Generate deterministic Git fixtures with expected revision-specific evidence | medium | terra | Terra is well suited to building reproducible repository fixtures and precise regression expectations. |
| CPEX-00006 | Define a revision-pinned evidence contract and three-pane interaction sketch | hard | opus | Opus is a strong fit for reconciling ambiguous CLI capabilities with rigorous evidence and revision semantics. |

### opus

| ID | Title | Complexity | Crew | Reason |
| --- | --- | --- | --- | --- |
| CPEX-00046 | Setup instructions and a rendered acceptance-demo path | low | gemini-flash | Gemini-flash handles the documentation and verification pass cheaply, since by this point the behaviour is settled and the work is writing it down accurately. |
| CPEX-00045 | Evaluation on real commit ranges and a declared performance envelope | medium | grok | Grok follows the verification suite with the real-repository evaluation, reusing its fixture-level understanding of where the system is likely to overclaim. |
| CPEX-00044 | Fixture verification suite for edges, spans, staleness, and dirty trees | hard | grok | Grok is effective at adversarial verification work, and this suite's job is to try to catch the rest of the system asserting more than its evidence supports. |
| CPEX-00043 | Bounded change report: JSON export and readable static report | hard | terra | Terra suits export work, which is mechanical breadth over an already-fixed envelope plus one careful degraded-mode rule. |
| CPEX-00042 | Symbol search, indexing progress, and empty/error states | medium | terra | Terra is efficient at breadth-style slices like a full state inventory, where the work is covering every enumerated case rather than solving one hard problem. |
| CPEX-00041 | Readable path/table view, keyboard navigation, and narrow-screen usability | medium | luna | Luna is careful about completeness against an explicit checklist, which is what accessibility parity needs more than it needs invention. |
| CPEX-00040 | Relationship filters with explanations for what disappeared | medium | terra | Terra handles rule-dense UI state well, and the filter-explanation requirement is precise enough to implement without architectural latitude. |
| CPEX-00039 | Candidate tests with preserved provenance categories | medium | grok | Grok is a good fit for a self-contained classification slice where the main requirement is keeping three provenance categories from being flattened together. |
| CPEX-00038 | Reachable entry points and explanatory evidence paths | hard | opus | Opus takes the reachability slice because the value is in the epistemic framing — distinguishing bounded from exhaustive, evidence from proof — not in the traversal code. |
| CPEX-00037 | Relationship neighborhood queries with on-demand expansion and visible truncation | hard | sol | Sol already owns the adapter and snapshot layers, so the bounded traversal and caching work sits naturally on top of code it wrote. |
| CPEX-00036 | Revision-correct source and diff evidence viewer | hard | sonnet | Sonnet continues on the viewing surface for consistency with the shell, and the revision-correctness rules here are explicit enough to implement directly. |
| CPEX-00035 | Three-pane application shell and change-list pane | medium | sonnet | Sonnet is the right fit for the primary UI scaffold: substantial component work against a settled contract, where throughput matters more than novel design. |
| CPEX-00034 | Changed file and symbol model with rename evidence and preserved ambiguity | hard | luna | Luna is well suited to the base/head bookkeeping here, where the main discipline is refusing to over-resolve ambiguous correspondence. |
| CPEX-00033 | Isolated snapshot materialization and per-side index lifecycle | hard | sol | Sol takes the snapshot and index lifecycle because correctness here is about process, caching, and invalidation discipline, which is its strongest mode. |
| CPEX-00032 | Local repository open, revision selection, and explicit comparison semantics | medium | luna | Luna is reliable on precise Git semantics where the risk is mislabelling rather than architecture, and this slice is mostly getting ref resolution and mode labelling exactly right. |
| CPEX-00031 | Loopback service skeleton with explicit repository scope and untrusted-content handling | hard | opus | Opus owns the trust boundary because repository content is untrusted and the scope, token, and no-execution guarantees are the slice where a subtle miss is most costly. |
| CPEX-00030 | Deterministic fixture repositories covering the hard graph cases | medium | terra | Terra handles well-specified, high-volume generation work efficiently, and this slice is mostly careful enumeration against an already-fixed contract. |
| CPEX-00029 | orbit-graph CLI adapter with a versioned, non-shell command contract | hard | sol | Sol is a strong systems implementer and this slice is disciplined subprocess and contract plumbing against a fixed external CLI rather than open-ended design. |
| CPEX-00028 | Evidence contract: shared data model for snapshots, changes, and evidence edges | hard | opus | Opus gets the foundational contract because every other slice inherits these shapes and the base/head and provenance distinctions are the easiest thing to get subtly wrong. |

### gemini-flash

| ID | Title | Complexity | Crew | Reason |
| --- | --- | --- | --- | --- |
| CPEX-00027 | Developer setup guide and reference runbook | low | sol | Sol writes crisp, systematic technical documentation and developer runbooks with precision and clarity. |
| CPEX-00026 | Product polish: keyboard navigation, search, and error/empty states | low | gemini-flash | Gemini-flash provides fast turnaround on UI usability improvements, shortcut handlers, and user feedback states. |
| CPEX-00025 | Acceptance demo and end-to-end integration test harness | medium | luna | Luna is the strongest choice for thorough end-to-end verification, fixture assertion suites, and regression testing. |
| CPEX-00024 | Standalone change report exporter | low | gemini-flash | Gemini-flash rapidly formats clean, portable Markdown and standalone HTML export templates with embedded assets. |
| CPEX-00023 | Revision-pinned source and diff viewer component | medium | sonnet | Sonnet provides reliable frontend code rendering, syntax highlighting, and accurate side-by-side diff positioning. |
| CPEX-00022 | Focused relationship explorer and accessible path/table component | hard | opus | Opus excels at designing intuitive mental models for complex relational graphs and accessible path-based explanations. |
| CPEX-00021 | Changed symbols list and filter view component | low | gemini-flash | Gemini-flash is efficient and fast at building clean, responsive list UI components with reactive client-side filtering. |
| CPEX-00008 | Three-pane application layout shell and revision selector UI | medium | sonnet | Sonnet delivers polished, accessible web UI architecture and seamless state management across multi-pane layouts. |
| CPEX-00005 | Multi-hop impact traversal and evidence path engine | hard | opus | Opus delivers deep reasoning needed for complex graph traversal, semantic categorization, and path confidence ranking. |
| CPEX-00004 | Changed symbol detection and diff correlation service | medium | sonnet | Sonnet combines backend precision with UI-ready data modeling to handle complex diff and symbol attribution. |
| CPEX-00003 | Isolated snapshot manager and orbit-graph CLI adapter | hard | grok | Grok is ideal for robust CLI subprocess adapters, stream parsing, and isolated worktree process management. |
| CPEX-00002 | Local loopback server with scoped Git repository service | medium | terra | Terra specializes in secure systems infrastructure, safe process sandboxing, and loopback service boundaries. |
| CPEX-00001 | Deterministic Git fixture repositories and ground-truth baselines | medium | luna | Luna excels at crafting comprehensive test fixtures and establishing reliable ground-truth baselines for edge cases. |
| CPEX-00000 | Shared evidence data contract and schema definitions | medium | sol | Sol provides rigorous type-level modeling and schema definitions ensuring an unambiguous data contract across all layers. |

