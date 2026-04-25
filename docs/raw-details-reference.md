# Raw Details Reference

**Status:** technical reference

This document answers one question:
> what does the app store, and what do the main structured payloads contain?

Trade Proposer App stores diagnostic metadata alongside runs, signals, plans, outcomes, and shared context workflows.

## Structured pipeline payloads

The app-native pipeline persists a structured per-ticker JSON object as `analysis_json`.

### `analysis_json`
Main sections:
- `metadata` — timestamps, version, ticker
- `trade` — direction, confidence, entry, stop, take profit
- `summary` — digest or LLM narrative plus generation metadata
- `news` — items, feed usage, feed errors, counts, and keyword diagnostics
- `signals` — optional cross-source signal payloads
- `social` — social/Nitter diagnostics when enabled
- `sentiment` — ticker sentiment plus shared macro/industry inputs
- `context_flags` — boolean context tags
- `feature_vectors` — `raw` and `normalized` values
- `aggregations` and weight maps — derived score breakdowns
- `diagnostics` — problems, provider failures, summary errors

### `analysis_json.sentiment`
This section mixes live ticker sentiment with shared macro and industry inputs.

Typical shape:
- `macro`
- `industry`
- `ticker`
- `enhanced`
- `coverage_insights`
- `keyword_hits`

Common macro/industry fields include:
- `snapshot_id`
- `context_snapshot_id`
- `subject_key`
- `label`
- `score`
- freshness and source metadata
- optional context summary/event fields

Current context-event payloads may also include fields such as:
- `persistence_state`
- `state_transition`
- `catalyst_type`
- `trigger_actor`
- `trigger_actor_role`
- `trigger_source_type`
- `market_interpretation`
- `state_change_reason`
- `evidence_direction`
- `evidence_samples`

`score` is a heuristic 0-100 confidence-style value, not a probability.

Context events may also carry `saliency_weight`, a normalized 0-1 prominence score.

### Other stored payloads
Common related payloads include:
- `raw_output`
- `feature_vector_json`
- `normalized_feature_vector_json`
- `aggregations_json`
- `confidence_weights_json`
- `summary_method`

## Redesign-native trade objects

The redesign path persists:
- `TickerSignalSnapshot`
- `RecommendationPlan`
- `RecommendationPlanOutcome`
- `RecommendationDecisionSample`

### `TickerSignalSnapshot`
Typical stored themes:
- signal status and direction
- attention and shortlist state
- cheap-scan/deep-analysis diagnostics
- transmission summary and warnings
- source breakdown and supporting diagnostics

### `RecommendationPlan`
Typical stored themes:
- action, confidence, entry, stop, target, horizon
- thesis and rationale
- evidence summary
- signal breakdown (includes `intended_action` for phantom-trade-eligible `no_action` plans)
- calibration review
- transmission summary
- warnings and diagnostics
- derived live-execution fields such as `broker_order_id`, `broker_order_status`, `effective_evaluation`, and `effective_evaluation_source` when Alpaca execution records exist

### `RecommendationPlanOutcome`
Typical stored themes:
- entry touched, stop hit, target hit
- fixed-horizon returns
- near-entry-miss diagnostics for unfilled plans (`entry_miss_distance_percent`, `near_entry_miss`, `direction_worked_without_entry`)
- favorable/adverse excursion
- realized holding period
- direction correctness
- confidence bucket
- setup family
- transmission-bias and context-regime slices used in calibration review

Outcome values include `win`, `loss`, `expired`, `no_action`, `watchlist`, `phantom_win`, `phantom_loss`, and `phantom_no_entry`. Phantom outcomes are produced when a `no_action` or `watchlist` plan retained an intended direction and valid trade levels and is evaluated against real market data.

### `RecommendationDecisionSample`
A tuning and review snapshot stored for each generated plan.

Common fields include:
- decision type and action
- shortlist status and rank
- confidence, calibrated confidence, threshold, and gap
- benchmark fields such as `benchmark_status`, `benchmark_target_1d_hit`, `benchmark_target_5d_hit`, `benchmark_max_favorable_pct`, and `benchmark_evaluated_at`
- setup family, transmission bias, and context regime
- compact decision, signal, and evidence snapshots
- linked run/job/watchlist/ticker-signal identifiers

## Governed and labeled detail fields

Many payloads now carry both canonical keys and readable labeled detail objects.

Common examples include:
- relationship labels such as `type_label`, `target_label`, and `channel_label`
- transmission detail arrays such as `transmission_tag_details`, `primary_driver_details`, and `conflict_flag_details`
- exposure-channel detail arrays
- event detail objects for contradiction reason, persistence state, window hint, source priority, and recency bucket
- analytics detail objects such as `transmission_bias_detail`, `context_regime_detail`, and `slice_label`
- calibration and action labels such as `review_status_label`, `reason_details`, and `action_reason_label`

The purpose is simple: keep stored canonical keys stable while letting the UI render readable labels.

## Context and ontology fields

Important stored context/ontology fields include:
- `event_lifecycle_summary`
- `contradictory_event_labels`
- per-event lifecycle/status fields
- `ontology_profile`
- `sector_definition`
- `ontology_relationships`
- `matched_ontology_relationships`
- `ticker_relationship_edges`
- `matched_ticker_relationships`
- `expanded_queries` for industry context refreshes when ontology-driven query expansion is used

These support context detail views, recommendation transmission summaries, and relationship read-through UI.

## Run and workflow artifacts

Run artifacts vary by workflow type.

Examples:
- proposal generation — recommendation summaries and diagnostics
- evaluation — evaluation scope and result summary
- optimization — before/after fingerprint and backup metadata
- context refresh — created snapshot ids, scope, refresh summary, and context event metadata
- order execution — broker-order summary counts, warnings, and persisted order records

### `BrokerOrderExecution`
The persisted broker-order audit record stores the execution trail for paper-trading submissions.

Typical stored fields include:
- `broker` and `account_mode`
- `recommendation_plan_id` and `recommendation_plan_ticker`
- `run_id` and `job_id`
- `ticker`, `action`, `side`, `order_type`, `time_in_force`
- `quantity`, `notional_amount`, `entry_price`, `stop_loss`, `take_profit`
- `status`, `broker_order_id`, `client_order_id`
- `submitted_at`, `filled_at`, `canceled_at`, `updated_at`
- `request_payload_json`, `response_payload_json`
- `error_message`
- `created_at`, `updated_at`

The request payload stores the exact Alpaca order body, including the bracket-order structure and client order id.

## Retired support snapshot records

Older builds introduced `SupportSnapshot` records during context refresh workflows, but active builds persist context snapshots directly.

`SupportSnapshot` is now historical only. Common historical fields were:
- `id`
- `scope`
- `subject_key`
- `subject_label`
- `status`
- `score`
- `label`
- `computed_at`
- `expires_at`
- `coverage`
- `source_breakdown`
- `drivers`
- `signals`
- `diagnostics`
- `job_id`
- `run_id`

## Common diagnostics and timing fields

Frequently stored fields include:
- `warnings`
- `provider_errors`
- `problems`
- `news_feed_errors`
- `news_query_diagnostics`
- `summary_error` or `llm_error`
- `timing_json`
- `analysis_timestamp`

## Operational notes

- scoring weights live in `src/trade_proposer_app/data/weights.json`
- `/api/health/preflight` reports dependency readiness and shared-context freshness
- summary backends are configured in `/settings`
- the same stored payloads support the debugger, run detail, broker-orders review, recommendation review, ticker review, decision-sample review, and health views

## See also
- `recommendation-methodology.md`
- `features-and-capabilities.md`
- `operator-page-field-guide.md`
