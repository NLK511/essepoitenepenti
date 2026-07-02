# Ticker exposure ontology spec

**Status:** current and target behavior

## Current behavior

Every taxonomy ticker has an explicit exposure ontology profile. Plan-generation payloads carry bounded, auditable ontology context, but ontology output does not bypass calibration, actionability, broker, or risk gates.

## Target behavior

Ontology-enhanced context may get stronger decision influence only after realized/walk-forward evidence proves it improves on the prior taxonomy-only transmission path. Obsolete taxonomy-only plumbing should be cleaned up only after that validation passes.

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

The ontology file must contain one explicit profile for every ticker in the active taxonomy universe (`src/trade_proposer_app/data/taxonomy/tickers.json`). Curated profiles should be preserved; all remaining tickers may be generated from sector/industry taxonomy templates but must still be explicit, versioned, sourced, and auditable. Generated profiles must use conservative confidence and mixed/low directional defaults where the taxonomy does not support a specific directional claim. Sector/industry templates may mark a profile usable only when the exposure is a broadly accepted economic relationship for that industry class (for example, rate sensitivity for REITs/utilities or consumer-spending sensitivity for restaurants/travel/retail). Templates must not add ticker-specific facts, customers, suppliers, or catalysts unless those are already present in taxonomy data or curated profiles.

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

## Implementation status

Implemented current behavior:

- every taxonomy ticker has an explicit exposure ontology profile
- curated profiles are preserved and generated profiles are stamped with source/version metadata
- conservative sector/industry templates provide directional macro/event sensitivities when the relationship is broadly accepted for that industry class
- ticker deep analysis emits `ontology_context` inside `ticker_deep_analysis.transmission_analysis`
- plan `transmission_summary` and `signal_breakdown` carry `ontology_context`, pre-ontology alignment, coverage status, coverage reasons, matched exposures, and transmission paths
- alignment adjustment is bounded and auditable; it does not bypass calibration, actionability, broker, or risk gates

Still target / gated:

- realized outcome validation proving ontology-enhanced context is better than the prior taxonomy-only transmission path
- cleanup of obsolete taxonomy-only transmission plumbing after validation
- more curated company-level profiles where generated templates are too broad

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

## Deprecation and cleanup trigger

If validation shows the exposure ontology is better than the prior taxonomy-only transmission path, create a cleanup ticket/work item before enabling stronger ontology-based decision influence. The cleanup should remove or downgrade obsolete taxonomy-only plumbing rather than leaving two competing context systems.

Cleanup checklist after successful validation:

- identify all taxonomy-only transmission fallback paths still used in plan generation
- remove duplicate bias/alignment derivation that ignores `ontology_context`
- retire stale fields that only supported old context scoring, or mark them as backward-compatible audit fields
- update docs and operator field guides to describe ontology-first transmission
- keep old persisted plan rows readable without recomputing them
- add regression tests proving new plans contain `ontology_context` and no longer depend on old-only fallbacks when ontology coverage is usable
- re-run outcome/effectiveness evaluation after cleanup to confirm no regression

Until those criteria pass, the old taxonomy remains a base metadata layer and backward-compatible fallback, not an independently promoted decision layer.
