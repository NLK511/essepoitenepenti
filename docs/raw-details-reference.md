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
- signal breakdown
- calibration review
- transmission summary
- warnings and diagnostics

### `RecommendationPlanOutcome`
Typical stored themes:
- entry touched, stop hit, target hit
- fixed-horizon returns
- favorable/adverse excursion
- realized holding period
- direction correctness
- confidence bucket
- setup family
- transmission-bias and context-regime slices used in calibration review

### `RecommendationDecisionSample`
A tuning and review snapshot stored for each generated plan.

Common fields include:
- decision type and action
- shortlist status and rank
- confidence, calibrated confidence, threshold, and gap
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

These support context detail views, recommendation transmission summaries, and relationship read-through UI.

## Run and workflow artifacts

Run artifacts vary by workflow type.

Examples:
- proposal generation — recommendation summaries and diagnostics
- evaluation — evaluation scope and result summary
- optimization — before/after fingerprint and backup metadata
- context refresh — created snapshot ids, scope, and refresh summary

## Support snapshot records

Shared macro and industry refresh workflows still persist `SupportSnapshot` records.

Common fields:
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

These act as both reusable artifacts and audit objects.

## Common diagnostics and timing fields

Frequently stored fields include:
- `warnings`
- `provider_errors`
- `problems`
- `news_feed_errors`
- `summary_error` or `llm_error`
- `timing_json`
- `analysis_timestamp`

## Operational notes

- scoring weights live in `src/trade_proposer_app/data/weights.json`
- `/api/health/preflight` reports dependency readiness and shared-context freshness
- summary backends are configured in `/settings`
- the same stored payloads support the debugger, run detail, recommendation review, ticker review, decision-sample review, and health views

## See also
- `recommendation-methodology.md`
- `features-and-capabilities.md`
- `operator-page-field-guide.md`
