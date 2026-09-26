# Offline field inspections

Build an offline-first inspection app for building inspectors who work in
basements, plant rooms and new construction with no reliable signal. An
inspector downloads assigned sites, fills structured checklists with photos
and measurements while offline, and syncs later. Office staff review the
results and issue a signed report.

The first users are a small inspection firm: about 30 inspectors on
Android and iOS phones, and four office reviewers on desktop browsers. The
product replaces paper checklists and a shared spreadsheet. It does not
schedule inspectors or bill clients.

**Acceptance demo:** assign two sites to an inspector; put the phone in
airplane mode; complete one checklist with photos, a failed item and a
measurement; edit the same site's contact details on the web at the same
time; reconnect; see the checklist upload, the conflict on the contact
details presented and resolved, and a reviewer approve the inspection and
download its PDF report.

## Foundation

This checkout holds the sync server and the web review console. The mobile
client is a separate app built from this repository's `mobile/` directory as
a Progressive Web App; no native app store release is required for v1.

The firm's existing job system exposes a read-only site and assignment API,
documented in `docs/jobs-api.md`. Import sites and assignments from it. Do
not write back to it.

Checklist templates are authored by the office as JSON documents that follow
`docs/checklist-schema.md`. The app must render any valid template without a
code change.

## Required user workflow

1. An inspector signs in once while online and downloads their assigned
   sites, the checklist templates those sites need, and prior inspection
   results for reference.
2. Offline, the inspector opens a site, starts an inspection from its
   template, and records pass/fail/not-applicable items, numeric measurements
   with units, free-text notes and photos. Required items block completion.
3. The inspector can pause and resume an inspection, and the device survives
   app restarts and low storage without losing entered data.
4. On reconnect, the app uploads completed and in-progress work in the
   background, shows per-item sync status, and retries with backoff.
5. Office staff see incoming inspections, compare them with the previous
   inspection of the same site, request changes, and approve.
6. Approval produces a PDF report with the site, inspector, timestamps,
   every item and its answer, failed items first, photos with captions, and
   a signature block.
7. Staff can search inspections by site, inspector, date range and outcome,
   and export a CSV of failed items.

## Semantic contract

### Offline data and sync

- The device is the source of truth for an in-progress inspection until it
  is submitted. The server never silently overwrites local answers.
- Every change carries a device id, a monotonic per-device sequence number
  and a client timestamp. The server records its own receive time; ordering
  uses sequence numbers, not clocks.
- Uploads are idempotent. A retried upload of the same change must not
  duplicate answers, photos or audit entries.
- Photos upload separately from answers, resumably, and an inspection is not
  marked fully synced until its photos are stored and checksummed.
- Template versions are pinned per inspection. A template edited in the
  office after download does not change an inspection already started.

### Conflicts

- Site contact details can be edited on the web and on devices. Concurrent
  edits to different fields merge; concurrent edits to the same field are
  kept as a visible conflict for a reviewer, with both values and authors.
- Inspection answers belong to one inspector and do not merge. If the same
  inspection is edited on two devices by the same person, the later
  submission wins and the earlier one is kept in history.
- Deletions are soft and syncable.

### Audit and reports

- Every answer change, approval and change request is recorded in an
  append-only audit log with who, when, device and before/after values.
- A report is generated from the approved version and stored with a content
  hash. Regenerating an approved report yields the same PDF bytes.

## Engineering boundaries

Server: a single service with a relational database and object storage for
photos. Web console and PWA share one component library. Authentication by
email magic link plus a device token; no SSO in v1.

Photos may show people and private premises. Store them encrypted at rest,
strip location metadata unless the template asks for it, and never serve
them from a public URL.

No push notifications, scheduling, invoicing, native store releases or
third-party analytics in v1.

## Milestones

| Milestone | Reviewable result |
|---|---|
| 1. Data contract | Sync protocol, change log format, conflict rules, template renderer contract and fixture templates. |
| 2. Offline capture | PWA downloads assignments, captures a full inspection offline, and survives restarts. |
| 3. Sync | Idempotent upload, resumable photos, field-level merge and visible conflicts. |
| 4. Review and reports | Review console, compare with previous inspection, approval, deterministic PDF, search and CSV export. |
| 5. Hardening and handoff | Encryption at rest, audit log verification, soak test on flaky networks, setup docs and demo script. |

Fix the sync protocol and change-log format before splitting client and
server work.

## Validation

- Fixture templates covering every item type, required items, units,
  conditional sections and a template version change mid-inspection.
- Automated tests that replay the same change log in different orders and
  with duplicated uploads and reach the same server state.
- A network-fault harness: dropped connections mid-upload, a 20-minute
  outage, clock skew of several hours between device and server.
- Declare a reference device and dataset (500 sites, 20 photos per
  inspection) and keep the PWA usable on it.

The product is complete when the acceptance demo passes on a real phone and
a desktop browser. No production deployment.
