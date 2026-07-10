# Industry context quality and role plan

**Status:** completed and archived implementation plan

This archived plan records the completed industry-context honesty pass after ticker exposure ontology and mapped context scoring. Current behavior is governed by `specs/context-scoring-spec.md` and measured promotion decisions remain in `recommendation-quality-improvement-plan.md`.

## Current role

Industry context now has a narrower role than when this plan was first written.

It should provide:

- a readable operator backdrop
- fresh industry-specific evidence when available
- explicit degraded/blocked diagnostics when evidence is thin
- optional corroborating context for downstream analysis

It should not be treated as the primary ticker-exposure ontology. The ticker exposure ontology now carries the structured ticker/sector/macro transmission profile for fresh plan generation, while old taxonomy data remains base metadata/fallback.

## Why this still exists

The original failure mode is still valid:

- industry summaries can be readable even when evidence is thin
- fallback/empty-driver rows can look neutral instead of degraded
- decision logic should not receive positive confidence from weak industry evidence

The goal is now to make industry context safe and measurable, then decide whether any decision-affecting role remains useful after ontology validation.

## Non-goals

- not a replacement for ticker exposure ontology
- not a standalone score engine
- not a reason to add expensive data vendors before measuring usefulness
- not a source of positive confidence when evidence is missing or degraded

## Target behavior

Industry context should clearly answer:

1. is there real industry-native evidence?
2. is the evidence fresh or stale?
3. are active drivers present?
4. does the evidence corroborate or contradict the recommendation idea?
5. is the layer useful beyond ontology/taxonomy transmission?

If the answer is no, the system should say so plainly.

## Completed workstreams

### 1. Make fallback semantics explicit — completed

Implemented:

- stored and resolver payloads expose `evidence_state`, `coverage_state`, `context_quality_status`, notes, and neutral reasons;
- empty-driver summaries say no salient industry evidence was found;
- missing-snapshot resolver payloads are blocked/degraded, not neutral-looking;
- Context Review now surfaces quality/evidence/coverage badges, stale counts, and neutral reasons.

### 2. Improve evidence coverage conservatively — completed for current scope

Implemented:

- industry refresh uses shorter windows for event-heavy industries and longer windows for slower-moving industries;
- query expansion uses tracked tickers, ontology queries/themes/event vocab/risk flags, sector labels, companies, and peer industries;
- refresh metadata stores expanded queries and lookback diagnostics;
- replay/backfill still uses point-in-time request mode and does not invent evidence.

### 3. Align subject resolution with ontology — completed for current scope

Implemented:

- industry refresh references ontology/taxonomy as routing/query metadata;
- concrete tracked tickers, company names, and peer/industry labels are preferred when available;
- ticker-specific exposure mapping remains owned by `ContextExposureMapper` and ticker exposure ontology rather than duplicated inside industry context;
- old persisted rows remain readable through resolver/schema adapters.

### 4. Tighten decision contribution rules — completed

Implemented:

- positive industry support is zeroed when industry quality is degraded/blocked/failed/partial or evidence is missing;
- non-empty active drivers are required for decision-usable industry context;
- degraded/blocked snapshots remain visible caution context;
- source breakdown and signal diagnostics trace industry contribution through quality, evidence, coverage, score reasons, and mapped exposure.

### 5. Measure whether to keep a decision role — completed for readiness reporting

Implemented:

- Context Review and `scripts/report_industry_context_quality.py` report usable/degraded/blocked counts, coverage/evidence distributions, stale rows, active-driver rate, zero-confidence rows, and neutral reasons;
- outcome usefulness remains an ongoing recommendation-quality question, not an implementation gap;
- no wider positive industry role should be promoted unless recommendation-quality reports show value beyond ontology/transmission slices.

## Execution record

1. fallback semantics cleanup — completed
2. evidence coverage expansion — completed for current scope
3. ontology-aligned subject resolution — completed for current scope
4. decision contribution tightening — completed
5. usefulness measurement readiness — completed; promotion decisions moved to recommendation-quality review

## Promotion rule

Keep or expand industry context's decision-affecting role only if:

- usable snapshots materially outnumber fallback-only snapshots
- usable snapshots improve plan quality, calibration, or false-positive reduction
- operators can see exactly why a snapshot is usable
- the layer adds information beyond ticker exposure ontology

Shrink to backdrop if:

- it remains mostly readable prose without measurable outcome separation
- ontology/transmission context explains the relevant exposure more reliably

Retire its decision role if:

- it still resolves mostly to neutral/thin output after cleanup
- it does not improve measured outcomes

## See also

- `specs/ticker-exposure-ontology-spec.md`
- `recommendation-methodology.md`
- `recommendation-quality-improvement-plan.md`
