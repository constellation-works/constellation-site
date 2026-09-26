# Visual change explorer

Build a developer-facing application that explains a Git change through source
relationships: what changed, which callers or entry points may be affected, and
which tests have a defensible connection to it.

The first user is a developer trying to understand an unfamiliar PR or prepare
a review. The product should help them answer concrete questions without
manually issuing graph queries. It does not decide whether a PR is correct or
replace code review.

**Acceptance demo:** select two commits in a real repository; inspect the
changed symbols; follow a path from an affected entry point to a changed
function; open the corresponding diff/source location; inspect connected tests
and the limits of the evidence; switch revisions and verify that stale results
are not presented as current.

## Foundation

This checkout is the companion UI repository. Graph extraction and queries come
from the existing `orbit-graph` CLI, documented in
`docs/orbit-graph-cli.md`. Reuse that public CLI (JSON output) through a small
adapter. Do not reimplement a graph engine, and do not read `.orbit` to infer
relationships.

Keep the UI and adapter in this repository. Treat orbit-graph as an external
tool with a versioned command contract.

## Required user workflow

1. Open a user-selected local Git repository and select base/head revisions.
   Display the comparison semantics and resolve both refs to immutable SHAs.
2. Build or load the required graph snapshots. Show indexing status, included
   languages, ignored files, unsupported constructs, and freshness.
3. See changed files and symbols with additions, removals, modifications, and
   rename/move evidence where supported.
4. Select a symbol and inspect direct callers, callees, related modules,
   reachable entry points, and candidate tests.
5. Follow an explanatory path with relationship types and source evidence.
   Open exact source lines and the relevant side of the diff.
6. Filter relationship confidence, language, change kind, traversal depth, and
   scope. Show why an item disappears when a filter is applied.
7. Save or export a bounded change report with revision pins, evidence paths,
   unresolved areas, and source references.

Use a practical three-pane layout: change list, focused relationship view, and
source/diff evidence. A readable path/table view must remain available when the
graph is dense or a visual layout is inaccessible. Expand neighborhoods on
demand rather than rendering a whole-repository hairball.

## Semantic contract

### Revisions and changes

- Offer direct base-to-head comparison first. If PR-style merge-base comparison
  is offered, label it distinctly and show the actual effective base SHA. Never
  silently switch between them.
- Index immutable snapshots without checking out over the user's working tree.
- Base and head graphs remain distinct. Removed symbols and old callers require
  base evidence; added symbols require head evidence. Label which snapshot
  supports each path.
- Uncommitted files are excluded from the first version, with an explicit
  notice when the repository is dirty.
- Renames, splits, and signature changes can be ambiguous. Preserve uncertain
  correspondence rather than inventing stable symbol identity across versions.
- Reports must record both SHAs, extractor/schema versions, query options,
  index identity, and any truncated or unsupported scope.

### Impact evidence

- Distinguish an observed syntactic reference from a resolved call, heuristic
  match, import relationship, and user-selected association.
- Show a short evidence path for each affected entry point or candidate test.
  Every edge should link to a source location where available and identify its
  confidence/provenance.
- Static reachability is potential impact, not proof that a production path
  executes or a test covers the change.
- Candidate tests may come from explicit call paths, imports, or disclosed
  naming/file heuristics. Preserve those categories. Do not label proximity as
  measured coverage.
- “No path found” means no path in the available indexed evidence. Surface
  incomplete language support and unresolved symbols alongside that result.
- Depth, node, and time limits must produce visible truncation.

### Source navigation and reports

- Clicking a relationship opens the correct revision, file, and source line. A
  deleted symbol opens base-side content, not whatever is now at that line in
  head.
- Export JSON plus a readable static report. Include a controlled excerpt or
  precise source reference, not the entire repository by default.
- A report viewed without access to its repository must distinguish embedded
  evidence from unavailable source navigation.

## Engineering boundaries

Default to a local web UI with a small loopback service that can access local
Git and the orbit-graph CLI. Treat repository content as untrusted data.
Opening a repository must not run its hooks, builds, tests, package scripts, or
macros. Render source safely. Protect any local API that can read files with
explicit repository scope.

No GitHub authentication, hosted ingestion, public uploads, automated reviews,
PR mutations, test execution, or CI gating is required for v1.

## Milestones

| Milestone | Reviewable result |
|---|---|
| 1. Evidence contract | API inventory, snapshot/comparison semantics, minimal data contract, fixture repositories, and UI sketch. |
| 2. Real change slice | Local revision selection, changed-symbol list, one evidence path, and correct source/diff navigation. |
| 3. Complete exploration | Base/head separation, removed/renamed symbols, entry points, candidate tests, confidence filters, and bounded traversal. |
| 4. Product polish | Search, focused graph plus table view, indexing progress, empty/error states, report export, and keyboard/narrow-screen usability. |
| 5. Evaluation and handoff | Fixture correctness, a short evaluation on real commit ranges, setup instructions, and a rendered demo path. |

Separate snapshot extraction, graph adapter, source/diff viewer, and
relationship UI after the shared evidence contract is fixed.

## Validation

- Build deterministic fixture repositories covering direct calls, ambiguous
  same-name symbols, changed signatures, removed symbols, renamed files,
  changed tests, generated/unsupported code, cycles, and branch divergence.
- Verify displayed fixture paths against expected edges and revision-specific
  source spans. Exercise stale-index invalidation and a dirty working tree.
- Declare a reference hardware/repository envelope. Keep the UI responsive and
  cancelable during indexing.

The product is complete when a developer can perform the demo end to end
against a real local repository. No release tags or public deployment.
