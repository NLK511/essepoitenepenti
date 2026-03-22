# Shared Sentiment Snapshot Refactor

This document describes the recommended refactor for moving macro and industry sentiment out of per-ticker proposal execution and into reusable scheduled snapshots.

## Summary

Trade Proposer App should stop recomputing macro and industry sentiment inside every ticker proposal run. Those two scopes are largely shared across many recommendations, so the app should compute them on a schedule, persist them as auditable snapshots, and reuse them during proposal generation. Ticker sentiment should remain live and ticker-specific.

Target model:

- **Macro sentiment**: shared scheduled snapshot
- **Industry sentiment**: shared scheduled snapshot per industry/theme
- **Ticker sentiment**: computed during each proposal run
- **Proposal fusion**: combine the latest valid macro snapshot, latest valid industry snapshot, and fresh ticker sentiment

## Why this refactor is better

### Efficiency
Macro and industry inputs are shared across many tickers. Recomputing them inside every proposal run duplicates the same provider calls, parsing, and scoring work.

### Consistency
All tickers generated in the same time window should use the same macro baseline, and all tickers in the same industry should use the same industry baseline unless explicitly refreshed.

### Reliability
Shared scheduled snapshots reduce repeated dependency on external news providers and the local Nitter instance during proposal execution, making proposal runs faster and less fragile.

### Explainability
Operators can inspect:
- the macro snapshot used
- the industry snapshot used
- the live ticker sentiment
- the final fused sentiment

That is more traceable than recomputing everything ad hoc for each ticker.

## Architecture target

### Current shape
`proposal run -> fetch signals -> compute macro/industry/ticker inline -> recommendation`

### Target shape
`scheduled sentiment jobs -> persist macro/industry snapshots`

then

`proposal run -> load snapshots + compute ticker sentiment live -> fuse -> recommendation`

## Scope ownership

### Shared scheduled scopes
#### Macro
Examples:
- interest rates
- inflation
- central bank tone
- yields
- oil and commodities stress
- geopolitics
- risk-on / risk-off

#### Industry
Examples:
- semiconductors
- banks
- energy
- biotech
- cloud/software
- airlines

### Live per-proposal scope
#### Ticker
Examples:
- company earnings
- guidance changes
- analyst upgrades/downgrades
- legal issues
- management changes
- ticker-specific social chatter

## New persisted object

Introduce a reusable persisted snapshot model.

### `SentimentSnapshot`
Suggested fields:
- `id`
- `scope`: `macro` or `industry`
- `subject_key`: e.g. `global_macro`, `semiconductors`, `banks`
- `subject_label`
- `status`
- `score`
- `label`
- `computed_at`
- `expires_at`
- `coverage_json`
- `source_breakdown_json`
- `drivers_json`
- `signals_json`
- `diagnostics_json`
- `job_id` optional
- `run_id` optional

This snapshot should act as both cache and audit record.

## Freshness model

Use **schedule + TTL**.

### Recommended defaults
#### Macro
- refresh frequency: 2-3 times per day
- TTL: 6 hours

#### Industry
- refresh frequency: 1-2 times per day
- TTL: 8 hours

### Proposal behavior
When generating a proposal:
1. load latest valid macro snapshot
2. load latest valid industry snapshot for the ticker’s industry
3. compute fresh ticker sentiment
4. fuse them into the final sentiment layers

If a snapshot is missing or stale:
- use `NEUTRAL` / `0.0`
- emit an explicit warning
- do not invent fallback heuristics

This keeps the signal integrity policy intact.

## Fusion model after refactor

Proposal generation should consume:
- `macro_snapshot.score`
- `industry_snapshot.score`
- `ticker_sentiment.score`

Recommended first-pass weights for single-name stocks:
- macro: `0.20`
- industry: `0.30`
- ticker: `0.50`

Example:

```text
overall_sentiment =
  0.20 * macro_snapshot +
  0.30 * industry_snapshot +
  0.50 * ticker_live
```

That result can then feed the existing enhanced-sentiment stage that also uses summary tone and technical context.

## New workflow types

Add scheduled workflows for shared sentiment refresh.

### `MACRO_SENTIMENT_REFRESH`
Produces one shared macro snapshot.

### `INDUSTRY_SENTIMENT_REFRESH`
Produces one or more industry snapshots.

Preferred behavior:
- one orchestrator refresh job computes only industries needed by active watchlists/jobs
- or a single industry refresh run loops over the industries derived from active tickers

## Query strategy

### Macro refresh queries
Use shared macro queries, for example:
- Fed
- inflation
- CPI
- yields
- recession
- oil
- tariffs
- sanctions
- jobs report
- risk-on / risk-off

### Industry refresh queries
Use taxonomy-derived industry and theme keywords from `ticker_taxonomy.json`.

## Proposal payload changes

`analysis_json.sentiment` should distinguish snapshot-backed scopes from live scopes.

Example:

```json
{
  "sentiment": {
    "macro": {
      "source": "snapshot",
      "snapshot_id": 12,
      "subject_key": "global_macro",
      "score": -0.18,
      "label": "NEGATIVE"
    },
    "industry": {
      "source": "snapshot",
      "snapshot_id": 44,
      "subject_key": "semiconductors",
      "score": 0.27,
      "label": "POSITIVE"
    },
    "ticker": {
      "source": "live",
      "score": 0.41,
      "label": "POSITIVE"
    }
  }
}
```

## Failure semantics

### Missing macro snapshot
- score = `0.0`
- label = `NEUTRAL`
- warning = `macro snapshot unavailable`

### Missing industry snapshot
- score = `0.0`
- label = `NEUTRAL`
- warning = `industry snapshot unavailable for <industry>`

### Ticker sentiment failure
- score = `0.0`
- explicit warning
- proceed only if the broader recommendation policy allows it

## Services to add

### `SentimentSnapshotRepository`
Responsibilities:
- save snapshots
- fetch latest valid snapshot by scope and subject
- list snapshots for UI/debugging

### `MacroSentimentService`
Responsibilities:
- run macro queries
- fetch news/social signals
- compute macro sentiment
- persist snapshot

### `IndustrySentimentService`
Responsibilities:
- build industry query sets from taxonomy
- fetch signals
- compute industry sentiment
- persist snapshot

### `SentimentSnapshotResolver`
Responsibilities:
- resolve the latest valid macro and industry snapshots during proposal generation
- emit missing/stale warnings

## Scheduler and worker integration

The worker and scheduler should treat macro/industry refresh as normal first-class workflows. That keeps the app-native execution model and audit trail consistent with existing proposal, evaluation, and optimization jobs.

## UI additions

### Snapshot visibility
Add UI surfaces for:
- current macro snapshot
- current industry snapshots
- snapshot age and freshness
- source counts and coverage
- driver summaries and warnings

### Proposal detail view
Show:
- macro snapshot used
- industry snapshot used
- live ticker sentiment
- overall fused sentiment
- stale/missing indicators

## Migration plan

### Phase 1
Add snapshot persistence:
- domain model
- persistence model
- migration
- repository

### Phase 2
Implement macro refresh workflow and persistence.

### Phase 3
Implement industry refresh workflow and persistence.

### Phase 4
Refactor `ProposalService` to consume snapshots instead of computing macro and industry inline.

### Phase 5
Update UI, debugger views, and docs.

### Phase 6
Tune schedules, TTLs, and confidence weights based on evaluation outcomes.

## Recommended final state

The preferred steady-state architecture is:
- macro = shared scheduled snapshot
- industry = shared scheduled snapshot
- ticker = live per proposal
- overall sentiment = fused at proposal time
- missing/stale data = explicit neutral outputs with diagnostics

This design is more scalable, more consistent, and easier to audit than recomputing macro and industry sentiment inside every ticker proposal run.
