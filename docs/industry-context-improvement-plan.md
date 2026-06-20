# Industry context quality and role plan

**Status:** active plan

This is the working plan for keeping industry context honest after the ticker exposure ontology work.

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

## Workstreams

### 1. Make fallback semantics explicit

Deliverables:

- add or normalize an explicit `evidence_state` / `coverage_state` field in stored snapshot payloads
- make empty-driver summaries say “no salient industry evidence found” or equivalent
- keep resolver fallback payloads blocked/degraded, not neutral-looking
- ensure UI-facing notes distinguish missing snapshot, stale snapshot, and thin snapshot

Acceptance:

- empty-driver rows cannot look like meaningful neutral evidence
- degraded/blocked status is visible in payloads and UI surfaces

### 2. Improve evidence coverage conservatively

Deliverables:

- support longer fetch windows for slower-moving industries
- keep shorter windows for event-heavy industries
- expand query generation from tracked tickers, peers, ontology themes, and company names
- make replay/backfill use the same window rules as live refresh

Acceptance:

- coverage improves without inventing relationships
- provider/query diagnostics show why evidence was or was not found

### 3. Align subject resolution with ontology

Deliverables:

- use ontology/taxonomy relationships to route industry evidence where appropriate
- prefer concrete company/peer read-through over generic sector language
- avoid duplicating ontology logic inside industry context

Acceptance:

- industry context references ontology/taxonomy as routing metadata, not as fabricated evidence
- old persisted rows remain readable

### 4. Tighten decision contribution rules

Deliverables:

- require non-empty active drivers before any positive industry contribution
- require usable quality before any confidence influence reaches plan framing
- keep degraded/blocked snapshots as explicit caution context
- trace every contribution to concrete evidence

Acceptance:

- industry context cannot boost confidence from fallback prose
- contradictory/degraded evidence is visible and conservative

### 5. Measure whether to keep a decision role

Deliverables:

- report usable vs degraded/blocked snapshot counts
- track active-driver rate, zero-confidence rate, and fallback reasons
- compare outcomes for usable vs non-usable industry context
- compare industry context slices against ontology/transmission slices

Acceptance:

- keep a decision role only if industry context adds measured value beyond ontology/taxonomy context
- otherwise shrink it to readable backdrop plus diagnostics

## Execution order

1. fallback semantics cleanup
2. evidence coverage expansion
3. ontology-aligned subject resolution
4. decision contribution tightening
5. usefulness measurement and keep/shrink decision

## Success criteria

Keep industry context decision-affecting only if:

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
