# Ontology Enrichment Plan

**Status:** active implementation plan

This page tracks the work needed to turn the current ticker taxonomy into a more useful ontology for industry coverage, query generation, transmission reasoning, and operator-facing context summaries.

## Why this exists

Right now the app's ontology layer is still very thin.

The ontology started as `src/trade_proposer_app/data/ticker_taxonomy.json`. The active source now lives under `src/trade_proposer_app/data/taxonomy/`, with the old monolith kept as a fallback compatibility file. Before this work the ontology was tiny. That meant:

- industry coverage is too narrow
- refresh jobs only know about a small number of industries
- query generation is shallow
- context snapshots cannot represent much of the market structure
- operators see repeated labels like `Consumer Electronics` because the underlying taxonomy is too limited

This plan is here so progress can be tracked in one place instead of being scattered across chat history.

## Current baseline

Today the ontology is split into ticker, industry, sector, relationship, and event-vocabulary files, with the ticker layer still carrying fields like:

- `company_name`
- `aliases`
- `sector`
- `industry`
- `themes`
- `macro_sensitivity`
- `industry_keywords`
- `ticker_keywords`
- `exclude_keywords`

That is enough for a basic start, but not enough for broad multi-industry context coverage.

## Main goals

1. Expand market coverage beyond the current tiny starter set.
2. Make industry context represent multiple real industries, not one repeated default.
3. Improve search/query generation with better aliases and keywords.
4. Add explicit relationships that help transmission reasoning.
5. Add validation so ontology growth does not quietly degrade quality.
6. Keep the ontology understandable and maintainable rather than turning it into a giant messy dump.

## Work plan

### Phase 1 — Expand ticker and industry coverage

Goal: make the app aware of a practical starter universe of industries and representative tickers.

#### Tasks
- [x] Expand `src/trade_proposer_app/data/ticker_taxonomy.json` beyond the current starter set.
- [x] Add representative tickers for these industry groups:
  - [x] Semiconductors
  - [x] Software
  - [x] Cloud / internet platforms
  - [x] Consumer internet / digital ads
  - [x] Banks
  - [x] Payments
  - [x] Energy
  - [x] Industrials
  - [x] Airlines
  - [x] Autos / EV
  - [x] Healthcare / pharma
  - [x] Managed care
  - [x] Retail
  - [x] Consumer discretionary
  - [x] REITs / rate-sensitive real estate
  - [x] Utilities
  - [x] Materials / metals / mining
- [x] Make sure each new ticker has a sensible `sector` and `industry`.
- [x] Make sure each industry has enough ticker coverage that the grouping is not effectively single-name.

#### Exit criteria
- Industry refresh produces multiple distinct industries.
- Context review pages stop looking single-industry.
- Query coverage is noticeably broader in stored diagnostics.

### Phase 2 — Deepen ticker-level metadata

Goal: make each ticker entry more useful for search, grouping, and transmission logic.

#### Proposed additions per ticker
- [x] `subindustry`
- [x] `region`
- [ ] `exchange`
- [x] `market_cap_bucket`
- [x] `peers`
- [x] `suppliers`
- [x] `customers`
- [x] `exposure_channels`
- [x] `factor_tags`
- [x] `event_vocab`

#### Guidance
- Keep `ticker_keywords` focused on queryable names and common references.
- Keep `themes` for semantic grouping.
- Keep `exposure_channels` for transmission logic.
- Keep `event_vocab` for industry-native event framing.

#### Exit criteria
- Ticker profiles can support richer evidence gathering and clearer context explanations.
- Query generation can distinguish search terms from semantic tags.

### Phase 3 — Add industry-level definitions

Goal: stop relying only on ticker-derived industry labels and add explicit industry objects.

#### Proposed industry fields
- [x] canonical key
- [x] label
- [x] parent sector
- [x] industry keywords
- [x] themes
- [x] macro sensitivity
- [x] transmission channels
- [x] peer industries
- [x] risk flags
- [x] event vocabulary

#### Example uses
- better industry refresh queries
- better triage of relevant news
- clearer context detail views
- more consistent operator-facing wording across snapshots

#### Exit criteria
- Industry context can be generated from explicit industry definitions, not only from individual ticker records.
- Industry-level search and transmission logic becomes more stable.

### Phase 4 — Add relationship edges

Goal: make the ontology behave more like a real market-structure graph.

#### Relationship types to support
- [ ] `belongs_to_sector`
- [ ] `belongs_to_industry`
- [x] `peer_of`
- [x] `supplier_to`
- [x] `customer_of`
- [x] `benefits_from`
- [x] `hurt_by`
- [x] `sensitive_to`
- [ ] `exposed_to_theme`
- [ ] `linked_macro_channel`

#### Governed value registries
- [x] add governed `themes.json`
- [x] add governed `macro_channels.json`
- [x] normalize ticker / industry / sector taxonomy values against those registries inside the taxonomy service
- [x] validate that taxonomy themes and macro-channel references resolve to governed values
- [ ] migrate all remaining ontology relationship/channel fields to governed registries where practical

#### Example relationships
- Airlines → hurt by → oil
- REITs → sensitive to → long rates
- Semiconductors → sensitive to → export controls
- Consumer electronics → sensitive to → consumer spending
- Banks → sensitive to → curve shape and credit conditions

#### Exit criteria
- Transmission explanations can reference explicit relationships instead of only loose keyword overlap.
- Cross-industry reasoning becomes easier to debug.

### Phase 5 — Split the ontology into cleaner files

Goal: make maintenance easier as the ontology grows.

#### Proposed structure
- [x] `src/trade_proposer_app/data/taxonomy/tickers.json`
- [x] `src/trade_proposer_app/data/taxonomy/industries.json`
- [x] `src/trade_proposer_app/data/taxonomy/sectors.json`
- [x] `src/trade_proposer_app/data/taxonomy/relationships.json`
- [x] `src/trade_proposer_app/data/taxonomy/event_vocab.json`

#### Exit criteria
- The ontology is no longer trapped in one oversized file.
- File ownership and review are simpler.

### Phase 6 — Add validation and review tooling

Goal: make ontology growth safer.

#### Validation rules
- [x] Every ticker must have:
  - [x] `ticker`
  - [x] `company_name`
  - [x] `sector`
  - [x] `industry`
  - [x] `ticker_keywords`
- [x] Every industry must have:
  - [x] canonical key
  - [x] label
  - [x] sector
  - [x] query keywords
  - [x] transmission channels
- [x] Canonical keys should use one normalized style such as `consumer_electronics`.
- [x] Duplicate aliases and contradictory mappings should be flagged.
- [x] Very noisy or overly broad search keywords should be reviewable.

#### Tooling ideas
- [x] Add a validation script.
- [x] Add unit tests for taxonomy integrity.
- [x] Add a lightweight review report showing industries, tickers, missing fields, and possible noisy keywords.

#### Exit criteria
- Broken or low-quality ontology changes fail fast.
- It is easy to see what is incomplete.

## Suggested implementation order

1. Expand the ticker universe and industry coverage.
2. Add industry-level definitions.
3. Add validation and review tooling.
4. Add relationship edges.
5. Split files once the data model is stable enough.

This order is deliberate:

- coverage fixes the current product problem first
- explicit industry objects help context generation next
- validation keeps future growth under control
- relationship modeling is valuable, but it should not come before basic coverage and hygiene

## Starter universe candidates

These are sensible early additions.

### Technology
- Semiconductors: `NVDA`, `AMD`, `AVGO`, `TSM`, `INTC`
- Software: `MSFT`, `CRM`, `NOW`, `ADBE`
- Cloud / internet platforms: `AMZN`, `GOOGL`, `META`

### Financials
- Banks: `JPM`, `BAC`, `GS`, `MS`
- Payments: `V`, `MA`, `PYPL`

### Energy and materials
- Energy: `XOM`, `CVX`, `SLB`
- Materials / metals / mining: `FCX`, `NUE`, `AA`

### Industrials and transport
- Industrials: `CAT`, `DE`, `GE`
- Airlines: `DAL`, `UAL`, `AAL`

### Consumer
- Autos / EV: `TSLA`, `GM`, `F`
- Retail: `WMT`, `COST`, `TGT`, `HD`
- Consumer discretionary: `NKE`, `LULU`, `SBUX`

### Healthcare
- Pharma: `LLY`, `NVO`, `PFE`, `MRK`
- Managed care: `UNH`, `HUM`, `CVS`

### Rate-sensitive groups
- REITs: `PLD`, `O`, `SPG`
- Utilities: `NEE`, `DUK`

## Risks to avoid

- Do not dump in a huge unreviewed taxonomy just to increase row count.
- Do not mix semantic tags, query terms, and transmission relationships into one undifferentiated field.
- Do not let aliases become so broad that query noise overwhelms relevance.
- Do not rely on LLM-generated ontology changes without deterministic review.
- Do not build a graph so elaborate that nobody can maintain it.

## Progress log

Use this section to note concrete shipped steps.

- [x] Created this tracking page.
- [x] Expanded starter ticker coverage with a pragmatic multi-region large-cap universe across the U.S., Europe, and Asia-Pacific.
- [x] Added richer ticker metadata fields to the live taxonomy service and data file: `subindustry`, `region`, `domicile`, `market_cap_bucket`, `peers`, `suppliers`, `customers`, `exposure_channels`, `factor_tags`, and `event_vocab`.
- [x] Added explicit industry objects in the ontology data layer, then wired `src/trade_proposer_app/services/taxonomy.py` so industry refresh and query generation can use them directly instead of relying only on ticker-derived labels.
- [x] Added first-pass relationship modeling for `benefits_from`, `hurt_by`, and `sensitive_to` edges.
- [x] Started using ontology relationships directly inside `src/trade_proposer_app/services/industry_context.py` so industry context snapshots now store ontology profile metadata, matched transmission edges, taxonomy source mode, and relationship-aware prompt context.
- [x] Added derived ticker-level relationship edges from ticker profiles in `src/trade_proposer_app/services/taxonomy.py` for `peer_of`, `supplier_to`, and `customer_of`, then surfaced them in ticker deep-analysis transmission diagnostics.
- [x] Propagated ticker relationship provenance into watchlist/recommendation transmission payloads so recommendation review surfaces can show matched ticker relationships instead of keeping them buried only in raw analysis JSON.
- [x] Started using matched ticker relationships inside watchlist plan explanations so rationale, action-reason detail, invalidation text, and risk framing can mention supplier / customer / peer read-through when it actually matched the active evidence.
- [x] Added a reusable frontend ticker relationship read-through component and promoted matched relationship cards onto ticker and run-detail review surfaces so operators can inspect the actual relationship provenance more directly.
- [x] Added governed registry files at `src/trade_proposer_app/data/taxonomy/themes.json` and `src/trade_proposer_app/data/taxonomy/macro_channels.json`, then normalized taxonomy values against them in `src/trade_proposer_app/services/taxonomy.py`.
- [x] Updated taxonomy validation so ticker, industry, sector, and relationship macro-channel references are checked against the governed registries.
- [x] Split the active ontology into `src/trade_proposer_app/data/taxonomy/` with separate `tickers.json`, `industries.json`, `sectors.json`, `relationships.json`, and `event_vocab.json` files while keeping `ticker_taxonomy.json` as a backward-compatible fallback.
- [x] Added baseline taxonomy integrity tests for breadth, multi-region coverage, industry grouping behavior, explicit industry definitions, split-file loading, relationship availability, relationship-aware context behavior, and ticker-level relationship edges.
- [x] Added a validation script at `scripts/validate_taxonomy.py`.
- [x] Added a lightweight review report at `scripts/taxonomy_report.py`.

## Maintenance rule

When ontology-related work ships:
- update this page with completed items
- link to the concrete code or data files changed
- move old discarded approaches to `docs/archive/` if they become historical rather than active

## Related files

- `src/trade_proposer_app/data/taxonomy/tickers.json`
- `src/trade_proposer_app/data/taxonomy/industries.json`
- `src/trade_proposer_app/data/taxonomy/sectors.json`
- `src/trade_proposer_app/data/taxonomy/relationships.json`
- `src/trade_proposer_app/data/taxonomy/event_vocab.json`
- `src/trade_proposer_app/data/ticker_taxonomy.json` (fallback compatibility file)
- `src/trade_proposer_app/services/taxonomy.py`
- `src/trade_proposer_app/services/industry_context.py`
- `src/trade_proposer_app/services/industry_support.py`
- `src/trade_proposer_app/services/macro_context.py`
- `scripts/validate_taxonomy.py`
- `scripts/taxonomy_report.py`
- `tests/test_taxonomy.py`

## See also

- `recommendation-methodology.md`
- `architecture.md`
- `roadmap.md`
- `redesign/transmission-modeling-spec.md`
