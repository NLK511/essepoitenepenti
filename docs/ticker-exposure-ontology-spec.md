# Ticker exposure ontology spec

**Status:** active implementation

## Goal

Improve context transmission by representing each ticker as a point-in-time exposure graph rather than only a sector/industry label. The ontology should help plan generation answer:

1. which macro, industry, peer, supply-chain, revenue, or cost driver is active?
2. does it support or oppose a long setup?
3. how strong and well-sourced is the mapping?
4. what transmission path should operators audit?

## Non-goals

- Do not let ontology matches create unbounded confidence boosts.
- Do not treat AI-suggested or heuristic mappings as live-trusted without provenance and confidence.
- Do not replace market, technical, risk, or calibration gates.
- Do not make broker execution decisions from ontology output.

## Coverage requirement

The ontology file must contain one explicit profile for every ticker in the active taxonomy universe (`src/trade_proposer_app/data/taxonomy/tickers.json`). Curated profiles should be preserved; all remaining tickers may be generated from sector/industry taxonomy templates but must still be explicit, versioned, sourced, and auditable. Generated profiles must use conservative confidence and mixed/low directional defaults where the taxonomy does not support a specific directional claim.

## Data model

A ticker exposure profile is versioned and may contain:

- `ticker`
- `company_name`
- `sector`, `industry`, `subindustry`
- `business_summary`
- `revenue_drivers`
- `cost_drivers`
- `customer_segments`
- `geographic_exposure`
- `macro_sensitivities`
- `event_sensitivities`
- `peers`, `suppliers`, `customers`, `related_etfs`
- `setup_family_relevance`
- `confidence_score`
- `source`
- `version`
- `updated_at`

Sensitivity entries must be directional:

```json
{
  "factor": "interest_rates",
  "aliases": ["rates", "treasury yields"],
  "direction_if_factor_rises": "negative",
  "strength": "medium",
  "rationale": "higher discount rates pressure long-duration growth multiples"
}
```

Event sensitivity entries must be similarly directional:

```json
{
  "event": "oil_price_increase",
  "aliases": ["oil prices rise", "fuel costs"],
  "direction_for_long": "negative",
  "strength": "high",
  "rationale": "higher jet fuel prices pressure airline margins"
}
```

## Runtime behavior

During ticker deep analysis:

1. Load the base ticker taxonomy profile.
2. Load any richer exposure profile for the ticker.
3. Match macro and industry context events against exposure aliases, factors, drivers, peers, suppliers, customers, and free-text context evidence.
4. Emit `ontology_context` in `ticker_deep_analysis.transmission_analysis`.
5. Include matched exposures and transmission paths in downstream `transmission_summary` and `signal_breakdown`.
6. Apply only a bounded alignment adjustment:
   - positive support is capped conservatively
   - negative/headwind support may reduce alignment more strongly
   - no match means no adjustment

## Required output fields

`ontology_context` must include:

- `coverage_status`: `usable`, `degraded`, or `missing`
- `profile_version`
- `source`
- `confidence_score`
- `matched_exposure_count`
- `directional_support`: `supports_long`, `against_long`, `mixed`, or `unknown`
- `alignment_adjustment_percent`
- `transmission_paths`
- `matched_exposures`
- `warnings`

## Safety rules

- Missing ontology must be explicit and neutral.
- Sparse profiles must be `degraded`, not `usable`.
- Positive adjustment must require at least one medium/high confidence directional match.
- Negative adjustment may use medium/high headwind matches as a guardrail.
- All adjustments must be bounded and auditable.

## Generation

The repository must include a deterministic generator:

```text
scripts/generate_ticker_exposure_ontology.py
```

The generator must:

- read all taxonomy tickers
- preserve curated/provider-backed profiles
- generate conservative profiles for every missing ticker
- stamp source/version/update metadata
- keep generated low-confidence mixed mappings when directionality is unknown

## Validation and effectiveness

The first implementation must include an effectiveness report that compares old context transmission with ontology-enhanced transmission across recent persisted plans where possible:

- presence of usable ontology context
- matched exposure rate
- mixed-bias rate before/after ontology
- tailwind/headwind differentiation before/after ontology
- plan outcome win rate/EV by ontology directional support when outcomes exist

Promotion criteria for stronger live use:

- matched exposure rate is meaningfully above zero for active tickers
- mixed-bias rate decreases without increasing contradiction failures
- ontology-supported tailwinds/headwinds show outcome separation in walk-forward or realized outcomes
- operator-facing paths are sufficiently clear to audit
