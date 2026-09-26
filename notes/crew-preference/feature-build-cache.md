# Shared build cache

Build a self-hosted remote cache for a monorepo build tool so that developers
and CI machines reuse each other's compiled outputs. Today every CI job and
every laptop rebuilds from scratch; a clean build of the main repository takes
about 40 minutes.

The first users are one engineering team: about 60 developers and a CI fleet
of 30 ephemeral runners, all on the same private network. The cache must make
builds faster without ever making them wrong. It does not schedule builds or
execute actions remotely.

**Acceptance demo:** run a clean build on CI and watch it populate the cache;
run the same commit on a developer laptop and see most actions served from
the cache with the time saved reported; change one source file and see only
the affected actions rebuild; corrupt one stored blob on disk and see the
client detect it, fall back to building locally and report the corruption;
revoke a CI token and see its writes rejected while reads continue.

## Foundation

This checkout holds the cache server and its admin CLI. The build tool's
client already speaks the remote cache protocol documented in
`docs/cache-protocol.md`. Implement the server side of that protocol exactly;
do not change or fork the client.

The server is written in Rust (`server/`). The admin CLI is part of the same
workspace (`admin/`). Storage backends sit behind one trait.

## Required user workflow

1. An operator starts the server with a config file naming a storage backend,
   size limits and token store, and sees a health endpoint go green.
2. The operator issues tokens with scopes (`read`, `write`, `admin`) and
   optional expiry, and revokes them. Tokens are shown once.
3. CI runners and laptops point the build tool at the cache and get hits
   without any other change.
4. The server evicts cold entries to stay under its size limit and reports
   what it evicted.
5. The operator can see hit rate, bytes served, bytes stored, upload errors,
   latency percentiles and top missing keys, per token and overall.
6. The operator can pause writes, drain the server for maintenance, and
   verify the integrity of all stored blobs in the background.

## Semantic contract

### Correctness

- Blobs are content-addressed by SHA-256. The server verifies the digest of
  every upload before making it visible, and rejects mismatches.
- An action result may only reference blobs that exist when it is stored.
  Readers never see an action result whose outputs are missing.
- Eviction never removes a blob referenced by an action result that is still
  stored; action results and their blobs are evicted together.
- Concurrent uploads of the same blob are safe and store it once.
- A partial or interrupted upload is never visible.

### Access and isolation

- Writes require a `write` token. Reads may be anonymous only if the config
  explicitly allows it.
- Namespaces (`instance_name` in the protocol) are isolated: a key in one
  namespace is invisible from another.
- Tokens are stored hashed. Logs never contain tokens or blob contents.

### Operation

- The server stays available for reads while an integrity scan or eviction
  runs.
- Backends: local disk (required), and one S3-compatible object store
  (required). Both pass the same conformance suite.
- Metrics are exposed in Prometheus text format. Structured JSON logs.

## Engineering boundaries

A single server process; horizontal scaling is out of scope for v1, but no
design choice should make it impossible later. Runs as a container and as a
systemd service. TLS terminates at the server or at a reverse proxy,
configurable.

No remote execution, no web UI beyond a read-only status page, no multi-tenant
billing.

## Milestones

| Milestone | Reviewable result |
|---|---|
| 1. Protocol core | gRPC and HTTP endpoints from the protocol doc against an in-memory store, with the client's conformance tests passing. |
| 2. Storage | Disk and S3-compatible backends behind one trait, atomic upload, digest verification, shared conformance suite. |
| 3. Eviction and integrity | Size-bounded LRU with action-result consistency, background integrity scan, drain and pause-writes. |
| 4. Access and observability | Scoped tokens, admin CLI, namespaces, metrics, status page, structured logs. |
| 5. Proving it | Load test at CI scale, a benchmark on the real repository, a fault-injection run, packaging and an operator runbook. |

Settle the storage trait and the upload/visibility rules before backend work
splits.

## Validation

- A conformance suite that every backend runs: concurrent same-key uploads,
  truncated uploads, digest mismatch, missing referenced blob, eviction under
  load.
- A fault-injection harness: kill the server mid-upload, fill the disk, make
  the object store return errors and slow responses.
- A load test with 30 concurrent clients replaying a recorded CI build.
- Report the real repository's clean, warm and one-file-changed build times
  with and without the cache.

The product is complete when the acceptance demo passes against the real
repository. No public release.
