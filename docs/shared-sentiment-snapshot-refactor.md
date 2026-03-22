# Shared Sentiment Snapshot Refactor

## Status

This refactor is implemented.

Trade Proposer App now computes macro and industry sentiment through dedicated refresh workflows, persists the results as `SentimentSnapshot` records, reuses the latest valid snapshots during proposal generation, and exposes snapshot freshness through health/preflight and the UI.

## What remains relevant

The design intent from the original plan is still the right one:
- macro sentiment should be shared
- industry sentiment should be shared
- ticker sentiment should remain live per proposal
- missing or stale snapshots should produce explicit neutral/warning behavior

## Why this document is short now

The original long-form proposal became redundant once the feature shipped. The live references for the current behavior are now:
- `docs/architecture.md`
- `docs/features-and-capabilities.md`
- `docs/raw-details-reference.md`
- `docs/roadmap.md`

If the snapshot model changes materially in the future, add a fresh design note that documents the delta rather than restoring the old implementation plan.
