# Ontology Enrichment Plan

**Status:** active implementation plan

This page tracks the work needed to turn the current ticker taxonomy into a more useful ontology for industry coverage, query generation, transmission reasoning, and operator-facing context summaries.

## Why this exists

Right now the app's ontology layer is still very thin.

The main source is `src/trade_proposer_app/data/ticker_taxonomy.json`, and today it only has a very small starter set. That means:

- industry coverage is too narrow
- refresh jobs only know about a small number of industries
- query generation is shallow
- context snapshots cannot represent much of the market structure
- operators see repeated labels like `Consumer Electronics` because the underlying taxonomy is too limited

This plan is here so progress can be tracked in one place instead of being scattered across chat history.

## Current baseline

Today the ontology is mostly a per-ticker metadata file with fields like:

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
- [ ] Expand `src/trade_proposer_app/data/ticker_taxonomy.json` beyond the current starter set.
- [ ] Add representative tickers for these industry groups:
  - [ ] Semiconductors
  - [ ] Software
  - [ ] Cloud / internet platforms
  - [ ] Consumer internet / digital ads
  - [ ] Banks
  - [ ] Payments
  - [ ] Energy
  - [ ] Industrials
  - [ ] Airlines
  - [ ] Autos / EV
  - [ ] Healthcare / pharma
  - [ ] Managed care
  - [ ] Retail
  - [ ] Consumer discretionary
  - [ ] REITs / rate-sensitive real estate
  - [ ] Utilities
  - [ ] Materials / metals / mining
- [ ] Make sure each new ticker has a sensible `sector` and `industry`.
- [ ] Make sure each industry has enough ticker coverage that the grouping is not effectively single-name.

#### Exit criteria
- Industry refresh produces multiple distinct industries.
- Context review pages stop looking single-industry.
- Query coverage is noticeably broader in stored diagnostics.

### Phase 2 — Deepen ticker-level metadata

Goal: make each ticker entry more useful for search, grouping, and transmission logic.

#### Proposed additions per ticker
- [ ] `subindustry`
- [ ] `region`
- [ ] `exchange`
- [ ] `market_cap_bucket`
- [ ] `peers`
- [ ] `suppliers`
- [ ] `customers`
- [ ] `exposure_channels`
- [ ] `factor_tags`
- [ ] `event_vocab`

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
- [ ] canonical key
- [ ] label
- [ ] parent sector
- [ ] industry keywords
- [ ] themes
- [ ] macro sensitivity
- [ ] transmission channels
- [ ] peer industries
- [ ] risk flags
- [ ] event vocabulary

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
- [ ] `peer_of`
- [ ] `supplier_to`
- [ ] `customer_of`
- [ ] `benefits_from`
- [ ] `hurt_by`
- [ ] `sensitive_to`
- [ ] `exposed_to_theme`
- [ ] `linked_macro_channel`

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
- [ ] `src/trade_proposer_app/data/taxonomy/tickers.json`
- [ ] `src/trade_proposer_app/data/taxonomy/industries.json`
- [ ] `src/trade_proposer_app/data/taxonomy/sectors.json`
- [ ] `src/trade_proposer_app/data/taxonomy/relationships.json`
- [ ] `src/trade_proposer_app/data/taxonomy/event_vocab.json`

#### Exit criteria
- The ontology is no longer trapped in one oversized file.
- File ownership and review are simpler.

### Phase 6 — Add validation and review tooling

Goal: make ontology growth safer.

#### Validation rules
- [ ] Every ticker must have:
  - [ ] `ticker`
  - [ ] `company_name`
  - [ ] `sector`
  - [ ] `industry`
  - [ ] `ticker_keywords`
- [ ] Every industry must have:
  - [ ] canonical key
  - [ ] label
  - [ ] sector
  - [ ] query keywords
  - [ ] transmission channels
- [ ] Canonical keys should use one normalized style such as `consumer_electronics`.
- [ ] Duplicate aliases and contradictory mappings should be flagged.
- [ ] Very noisy or overly broad search keywords should be reviewable.

#### Tooling ideas
- [ ] Add a validation script.
- [ ] Add unit tests for taxonomy integrity.
- [ ] Add a lightweight review report showing industries, tickers, missing fields, and possible noisy keywords.

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
- [ ] Expanded starter ticker coverage.
- [ ] Added industry-level ontology objects.
- [ ] Added ontology validation tooling.
- [ ] Added relationship modeling.
- [ ] Split the ontology into multiple files.

## Maintenance rule

When ontology-related work ships:
- update this page with completed items
- link to the concrete code or data files changed
- move old discarded approaches to `docs/archive/` if they become historical rather than active

## Related files

- `src/trade_proposer_app/data/ticker_taxonomy.json`
- `src/trade_proposer_app/services/taxonomy.py`
- `src/trade_proposer_app/services/industry_context.py`
- `src/trade_proposer_app/services/industry_support.py`
- `src/trade_proposer_app/services/macro_context.py`

## See also

- `recommendation-methodology.md`
- `architecture.md`
- `roadmap.md`
- `redesign/transmission-modeling-spec.md`
