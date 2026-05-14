# Industry context improvement plan

**Status:** active plan

This is the working plan for making industry context materially useful instead of mostly neutral.

## Why this exists

Current industry context does two jobs:
- give operators a readable backdrop summary
- supply bounded evidence to downstream analysis

Today it does the first job better than the second. The main failure mode is not empty prose; it is empty or thin evidence that still resolves to a neutral-looking output.

## Current baseline

Current repo snapshot audit:
- `industry_context_snapshots`: 2529
- `ok`: 1282
- `warning`: 1247
- `confidence_percent = 0`: 727
- `saliency_score = 0`: 727
- `active_drivers` empty: 1237
- `summary_text` empty: 0

Interpretation:
- about half the snapshots are effectively fallback/low-signal rows
- the system can summarize, but it does not reliably find enough industry-native evidence
- neutral payloads are too easy to misread as informative

## Goal

Make industry context a **bounded evidence input** that only influences decisions when it has real evidence.

## Non-goals

- not a replacement for ticker analysis
- not a standalone score engine
- not a requirement to add expensive data vendors first
- not a reason to keep neutral-looking fallback prose when evidence is missing

## Target behavior

Industry context should clearly answer:
1. is there a real industry driver?
2. is the driver fresh or stale?
3. is the evidence strong enough to matter?
4. does it reinforce or weaken the current recommendation idea?

If the answer is no, the system should say so plainly.

## Workstreams

### 1. Make fallback semantics explicit

Deliverables:
- replace neutral-looking fallback wording with explicit no-evidence wording
- separate `usable`, `degraded`, and `blocked` industry context states clearly
- keep empty-driver rows from looking like meaningful context
- preserve operator readability while removing false confidence cues

Files:
- `src/trade_proposer_app/services/industry_context.py`
- `src/trade_proposer_app/services/context_snapshot_resolver.py`
- `src/trade_proposer_app/services/context_quality.py` if the status rules need tightening

Checklist:
- [ ] add an explicit `evidence_state` / `coverage_state` field to the stored snapshot payload
- [ ] make empty-driver summaries say “no salient industry evidence found” or equivalent
- [ ] keep resolver fallback payloads blocked, not neutral-looking
- [ ] ensure UI-facing notes distinguish “missing snapshot” from “thin snapshot”

### 2. Improve evidence coverage

Deliverables:
- widen the evidence window for slower-moving industries
- keep the shorter window for event-heavy industries
- fetch from more relevant industry-shaped queries before falling back to generic industry text

Files:
- `src/trade_proposer_app/services/industry_context.py`
- `src/trade_proposer_app/services/news.py` if the windowing/routing belongs in shared news fetch logic
- `scripts/reconstruct_context.py` for replay/backfill parity if the same rules need to apply historically

Checklist:
- [ ] support a longer fetch window for slow-moving industries
- [ ] keep short windows for event-driven industries
- [ ] expand query generation from tracked tickers, sector peers, ontology themes, and company names
- [ ] make replay/backfill use the same window rules as live refresh

### 3. Improve subject resolution

Deliverables:
- better industry ↔ ticker ↔ peer mapping
- better ontology relationship matching
- better reuse of existing tracked-ticker coverage when direct industry coverage is thin

Files:
- `src/trade_proposer_app/services/taxonomy.py`
- `src/trade_proposer_app/services/industry_context.py`
- `src/trade_proposer_app/services/context_snapshot_resolver.py` if resolver output needs richer taxonomy detail

Checklist:
- [ ] expand peer and relationship lookup when industry coverage is weak
- [ ] prefer concrete company/peer read-through over generic sector language
- [ ] avoid inventing relationships when evidence is missing

### 4. Tighten confidence gating

Deliverables:
- only grant positive confidence lift when evidence is actually present
- reduce or remove confidence contribution from empty-driver rows
- keep contradictory or degraded coverage from looking stronger than it is

Files:
- `src/trade_proposer_app/services/industry_context.py`
- `src/trade_proposer_app/services/ticker_analysis_payloads.py`
- `src/trade_proposer_app/services/watchlist_transmission.py` if any transmission summaries need to reflect the new quality semantics

Checklist:
- [ ] require non-empty drivers before any confidence lift
- [ ] require usable quality before a positive contribution reaches plan framing
- [ ] keep degraded/blocked snapshots as explicit negative context
- [ ] ensure confidence changes are traceable to actual evidence

### 5. Measure usefulness and decide whether to keep it

Deliverables:
- track usable rate, active-driver rate, and zero-confidence rate
- compare plan outcomes for usable vs degraded/blocked industry context
- retire the decision role if the layer remains mostly neutral after the improvements

Files:
- `src/trade_proposer_app/api/routes/context.py` if we need a simple summary endpoint
- `src/trade_proposer_app/services/industry_context.py`
- `src/trade_proposer_app/services/recommendation_quality_summary.py` or a new report helper if outcome comparison needs its own view
- `tests/test_context_services.py`
- `tests/test_context_snapshot_resolver.py`
- `tests/test_proposals.py`
- `tests/test_repositories.py` if persisted payload shape changes

Checklist:
- [ ] add a simple report for usable vs blocked/degraded snapshot counts
- [ ] compare plan outcomes for usable vs non-usable industry context
- [ ] record the top fallback reasons
- [ ] make a retire/shrink decision after enough data

## Execution order

1. fallback semantics cleanup
2. evidence coverage expansion
3. subject-resolution improvements
4. confidence gating tightening
5. measurement and decision

## Success criteria

Keep industry context if:
- usable snapshots materially outnumber fallback-only snapshots
- usable snapshots improve plan quality or calibration
- operators can see why a snapshot is usable or not

Shrink it if:
- it remains useful only as a short backdrop note

Retire its decision role if:
- it still resolves mostly to neutral/thin output after the coverage and gating changes
- it does not improve measured outcomes

## Notes

This plan is intentionally conservative.
If the layer cannot become meaningfully informative, it should stay as a readable backdrop and stop pretending to be decision-grade evidence.
