# Transmission Modeling Spec

**Status:** active redesign reference

## Purpose

This doc describes how the redesign should model **context transmission** from macro events to industries and from industries to tickers.

It is not trying to build a full causal market model. It is trying to make context usage explicit, inspectable, and testable.

## Scope

This spec applies to redesign-native:
- `MacroContextSnapshot`
- `IndustryContextSnapshot`
- `TickerSignalSnapshot`
- `RecommendationPlan`
- watchlist shortlist logic
- calibration-aware action gating
- outcome review slices that depend on transmission

## Core design rule

Context must not be treated as a generic sentiment overlay.

Instead, the engine should answer:
1. **what active context is present?**
2. **which industries are exposed?**
3. **which tickers are exposed through which channels?**
4. **is the transmission direction supportive, hostile, mixed, or negligible?**
5. **over what window should that context plausibly matter?**

## Transmission objects

Every redesign-native ticker analysis should derive a structured transmission object with at least:
- `context_bias`: `tailwind | headwind | mixed | unknown`
- `alignment_percent`: 0-100
- `transmission_tags`: list of governed summary-tag keys
- `transmission_tag_details`: optional labeled detail array for operator/UI display
- `primary_drivers`: ranked list of governed driver keys
- `primary_driver_details`: optional labeled detail array for operator/UI display
- `industry_exposure_channels`: list of industry-level channel keys
- `industry_exposure_channel_details`: optional labeled detail array for operator/UI display
- `ticker_exposure_channels`: list of ticker-specific channel keys
- `ticker_exposure_channel_details`: optional labeled detail array for operator/UI display
- `expected_transmission_window`: `intraday | 1d | 2d_5d | 1w_plus | unknown`
- `catalyst_intensity_percent`: 0-100
- `conflict_flags`: list of governed explicit-conflict keys
- `conflict_flag_details`: optional labeled detail array for operator/UI display
- `decay_state`: `fresh | active | fading | stale | unknown`

The app may persist more fields, but these fields are the minimum redesign-native contract.

Lower-level event identifiers should remain on dedicated event-detail fields such as `macro_event_keys` and `industry_event_keys`; they should not be overloaded into the governed summary-tag or primary-driver lists.

The same readability pattern is useful on context-review objects too: event-level `transmission_channels` can be accompanied by `transmission_channel_details` so operator-facing pages are not forced to render raw canonical channel keys.

## Transmission pipeline

## 1. Event extraction
Macro and industry context services should normalize source items into reusable event keys.

Examples:
- `ecb_restrictive_bias`
- `europe_growth_pressure`
- `middle_east_escalation`
- `oil_supply_risk`
- `semiconductor_ai_demand_strength`
- `airline_cost_pressure`

Each extracted event should carry:
- source quality
- recency
- saliency score
- affected regions
- affected industries
- event direction hints
- confidence / evidence quality

## 2. Macro-to-industry mapping
Every macro event definition should specify a ranked set of industry transmission mappings.

Each mapping should include:
- `industry_key`
- `channel`
- `expected_direction`
- `strength`: `low | medium | high`
- `window`
- `notes`

Example:
- `oil_supply_risk`
  - airlines → cost pressure → negative → high → `2d_5d`
  - energy producers → commodity support → positive → high → `2d_5d`
  - chemicals → input cost pressure → negative → medium → `2d_5d`

Example:
- `ecb_restrictive_bias`
  - eurozone banks → margin support / loan-growth drag split → mixed → medium → `1w_plus`
  - real estate → financing pressure → negative → high → `1w_plus`
  - industrials → growth pressure → negative → medium → `1w_plus`

## 3. Industry-native transmission
Industry context should also emit industry-native drivers that do not require a macro origin.

Examples:
- foundry capacity tightness
- memory pricing rebound
- airline booking strength
- cloud spending acceleration
- drug trial readout

Each industry-native driver should specify:
- likely beneficiary profiles
- likely loser profiles
- timing window
- catalyst type: `earnings | product | regulation | supply_chain | pricing | guidance | conference | geopolitical | other`

## 4. Industry-to-ticker mapping
Ticker transmission should not rely only on sector membership.

Each ticker should be evaluated through explicit exposure channels such as:
- revenue sensitivity
- input-cost sensitivity
- rate sensitivity
- commodity sensitivity
- geographic revenue exposure
- supply-chain dependency
- beta / sympathy behavior
- balance-sheet sensitivity
- valuation-duration sensitivity
- catalyst read-through similarity

Ticker exposure should ideally be derived from a mix of:
- watchlist metadata
- taxonomy
- manually curated mappings
- later, more explicit issuer metadata

## Transmission scoring policy

## A. Direction policy
Each active driver should contribute one of:
- `tailwind`
- `headwind`
- `mixed`
- `neutral`

Direction should be relative to the proposed trade direction when possible.

Examples:
- bullish energy context for an energy producer long = `tailwind`
- same context for an airline long = not tailwind; likely `headwind`
- higher rates for a real-estate long = `headwind`

## B. Strength policy
Each driver contribution should be weighted by:
- event saliency
- source quality
- recency
- industry transmission strength
- ticker exposure strength
- horizon fit
- catalyst freshness

These inputs should be visible in diagnostics.

## C. Horizon fit policy
Transmission must be horizon-aware.

### `1d`
Prefer:
- fresh catalysts
- official releases
- company-specific news
- strong sympathy read-throughs
- urgent macro shocks

De-emphasize:
- slow macro themes with weak near-term triggerability

### `1w`
Prefer:
- persistent macro drivers
- industry pricing / demand changes
- post-event follow-through
- developing but still active catalysts

### `1m`
Prefer:
- regime persistence
- financing / valuation pressure
- policy shifts
- demand / supply trend continuation

## D. Decay policy
Every context driver should have a decay state.

Suggested interpretation:
- `fresh`: new and potentially underpriced
- `active`: still relevant and being confirmed
- `fading`: still present but with weakening marginal impact
- `stale`: should not materially influence plan promotion without new confirmation

Stale or fading drivers should reduce transmission influence for shorter horizons first.

## Conflict policy
The engine must explicitly detect and persist conflicts such as:
- strong technical setup + context headwind
- weak technical setup + strong catalyst tailwind
- macro tailwind + industry headwind
- industry tailwind + ticker-specific adverse news
- high alignment + poor execution quality

Suggested conflict tags:
- `technical_context_conflict`
- `macro_industry_conflict`
- `industry_ticker_conflict`
- `directional_conflict`
- `timing_conflict`
- `execution_conflict`

Conflicts should:
- lower confidence components where appropriate
- influence `no_action` decisions
- remain visible in operator payloads
- later become evaluation slices

## Recommendation-plan rules

## 1. When transmission should block action
Transmission should be able to block action when:
- `context_bias == headwind`
- alignment is low or negative for the proposed trade
- the active driver window fits the chosen horizon
- the driver evidence is strong enough
- the conflict is not offset by unusually strong ticker-specific evidence

This should remain explicit as `action_reason`, not hidden in confidence math alone.

## 2. When transmission should modulate but not block
Transmission should usually modulate, not fully block, when:
- context is mixed
- the event is fading
- evidence quality is weak
- horizon fit is poor
- the ticker catalyst is much more immediate than the broader context

## 3. Catalyst lane policy
The catalyst lane exists because context and catalysts can matter even when cheap scan is not dominant.

Catalyst-lane promotion should be favored when:
- catalyst intensity is high
- event freshness is high
- horizon fit is strong
- transmission is explainable
- technical structure is not broken even if not top-ranked

## Derived regime labels
For operator review and calibration slices, the engine should derive a compact regime label from transmission tags.

Current labels can include:
- `macro_dominant`
- `industry_dominant`
- `macro_and_industry`
- `catalyst_active`
- `context_plus_catalyst`
- `tailwind_without_dominant_tag`
- `headwind_without_dominant_tag`
- `mixed_context`

These labels are for review and gating support, not full macro regime theory.

## Minimum diagnostics to persist
At minimum, redesign-native ticker outputs should persist:
- top transmission drivers
- top negative transmission drivers
- top positive transmission drivers
- exposure channels used
- conflict flags
- decay state
- horizon fit assessment
- source-quality summary for the driving events
- explanation of why transmission was treated as tailwind/headwind/mixed

## Implementation sequence

## Near-term
1. enrich event definitions with affected industries, direction, and window
2. add explicit industry and ticker exposure channels
3. persist primary drivers and conflict flags in `transmission_summary`
4. make shortlist and plan-generation logic consume those fields directly
5. expose them in operator UI before making them more complex

## Medium-term
1. add explicit per-ticker exposure metadata
2. add event-decay scoring
3. add contradiction detection between macro/industry/ticker drivers
4. evaluate transmission slices against outcomes
5. tighten calibration-aware gating using only sufficiently supported cohorts

## Non-goals
This spec does not require:
- full factor-model forecasting
- automated position sizing
- autonomous execution
- claiming that every context mapping is causal or predictive

## Success criteria
This spec is helping if it produces:
- fewer decorative context fields
- clearer reasons for `no_action`
- more consistent operator explanations
- measurable differences in outcome quality between transmission-supported and transmission-conflicted plans
- less cheap-scan dominance in shortlist composition without replacing it with noise
