# Bank statement import and reconciliation

Add statement import and reconciliation to a small-business bookkeeping app.
Today owners type transactions in by hand from their bank's website. They
should be able to import statements from their banks, have most transactions
categorized for them, and reconcile each account to the bank's closing
balance with confidence that nothing was missed or counted twice.

The first users are owners of businesses with one to five bank and card
accounts and a few hundred transactions a month, working on a laptop, often
without accounting training. Their accountant reviews the books quarterly.
The feature does not connect to banks directly, file taxes or pay bills.

**Acceptance demo:** import a CSV from one bank and an OFX file from another
covering overlapping dates; see duplicates across the two files and against
existing hand-entered transactions detected and explained; accept suggested
categories and create a rule from a correction; split one transaction across
two categories; reconcile an account to the statement's closing balance, find
the one missing transaction the difference points to, and lock the period;
export the reconciled period for the accountant.

## Foundation

This checkout is the existing bookkeeping app: a server-rendered web app with
a relational database. The ledger model is documented in
`docs/ledger-schema.md`. Imported transactions become ordinary ledger entries;
do not create a parallel store.

Bank file formats vary. Support OFX 1.x and 2.x, QFX, and CSV. For CSV,
the user maps columns once per bank and the mapping is remembered.

## Required user workflow

1. The user uploads one or more statement files for an account. The app
   detects the format, shows a preview with parsed dates, amounts and
   descriptions, and flags rows it could not parse, before anything is
   written.
2. For a new CSV layout, the user maps columns, date format, sign convention
   and decimal separator, with a live preview; the mapping is saved for
   files from the same bank.
3. On import, the app matches each row against existing entries and against
   other rows in the same batch, and sorts them into new, likely duplicate
   and matched-to-existing, with the reason for each.
4. New transactions get suggested categories from the user's rules and
   history. The user accepts, corrects or splits them; a correction can
   become a rule.
5. The user reconciles an account for a statement period: enters or confirms
   the closing balance, ticks cleared transactions, and sees the difference
   narrow to zero. The app suggests which transactions explain a difference.
6. A reconciled period can be locked. Editing a locked transaction requires
   unlocking the period, which is recorded.
7. The user or the accountant exports a period as CSV and a PDF summary.

## Semantic contract

### Money and dates

- Amounts are stored as integer minor units with a currency code. No
  floating point anywhere in parsing, matching or totals.
- Dates are calendar dates in the account's time zone. Posted date and
  transaction date are distinct when the file provides both.
- Sign conventions are normalized on import: money out of the business is
  negative, whatever the file uses.

### Matching and duplicates

- Bank-provided transaction ids are used when present and stable. Otherwise
  a match uses date proximity, amount and a normalized description, and the
  confidence is shown.
- Nothing is deleted or merged automatically. Likely duplicates wait for the
  user; the user's decision is remembered so a re-import does not ask again.
- Importing the same file twice is a no-op, and the app says so.

### Categories and rules

- Rules match on description patterns, amount ranges and account, and have
  an explicit order. The app shows which rule produced a suggestion.
- Splits must sum exactly to the transaction amount.

### Reconciliation and audit

- Opening balance of a period equals the closing balance of the previous
  reconciled period, or the user states it and the app records that.
- Every import, match decision, rule change, reconciliation and unlock is in
  an audit trail the accountant can read.

## Engineering boundaries

Uploaded statements contain account numbers. Store only the last four digits
of account numbers, keep original files encrypted for 90 days for support and
then delete them, and never log file contents.

No bank APIs, open-banking aggregators, receipt scanning, multi-currency
conversion or tax reports in v1.

## Milestones

| Milestone | Reviewable result |
|---|---|
| 1. Import contract | Parsed-row model, money and date rules, parser interface, fixture statement files from several banks, UI sketch. |
| 2. Parsing and preview | OFX/QFX and mapped CSV parsing with preview and error rows, saved bank mappings. |
| 3. Matching | Duplicate and existing-entry matching with reasons, idempotent re-import, user decisions remembered. |
| 4. Categorizing and reconciling | Suggestions, rules with provenance, splits, reconciliation with difference hints, period locking. |
| 5. Handoff | Export for the accountant, audit trail view, retention job, accessibility pass, user guide. |

Settle the parsed-row model and money rules before parser and matching work
split.

## Validation

- Fixture files from at least five banks, including a CSV with a comma
  decimal separator, a file with split debit and credit columns, an OFX
  file with duplicate FITIDs, a statement crossing a daylight-saving change,
  and a file in the wrong encoding.
- Property tests: importing any fixture twice changes nothing; totals equal
  the file's own totals to the minor unit.
- A reconciliation walkthrough with a deliberately missing and a deliberately
  duplicated transaction.

The product is complete when the acceptance demo passes on the fixtures and on
one real anonymized statement set. No production release.
