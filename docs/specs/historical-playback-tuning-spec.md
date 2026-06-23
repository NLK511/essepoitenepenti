# Historical playback tuning spec

**Status:** current + target behavior

This spec defines the target replay mechanism used by future plan-generation tuning. It also records the current boundary: historical replay can prepare market inputs, while plan-generation tuning currently uses compact stored-plan eligible records rather than full per-candidate replay.

## Purpose

Historical playback tuning should answer:

> What would the current app logic do on historical point-in-time inputs if a candidate plan-generation config were active, and how would those generated plans resolve afterward?

The objective is edge discovery and safer autonomous tuning, not perfect reconstruction of old operator decisions.

## Supported experiment modes

### `stored_plan_rescore` — implemented

Current plan-generation tuning mode.

It:
- loads compact eligible records derived from existing `RecommendationPlan`, outcome, and decision-sample artifacts
- perturbs active plan-generation parameters
- rescales/reframes stored plan levels where supported
- scores candidate configs from compact outcome features

It does not:
- run the full historical replay service for each candidate
- regenerate all signals/plans from raw historical inputs
- use canonical intraday resolution for every adjusted candidate plan

### `current_code_point_in_time_replay` — target

Target tuning mode.

It must:
- iterate deterministic historical `as_of` slices
- load only generation inputs available at or before `as_of`
- run current cheap scan, deep analysis, signal generation, and plan generation
- apply a scoped candidate tuning config override without mutating live settings
- resolve generated plans using post-`as_of` bars through canonical plan-resolution semantics
- persist replay provenance and quality gates

This mode may use current code and current non-tuned settings. It is not required to reproduce old production configs unless explicitly run as an audit mode.

### `historical_code_replay` — future optional

An audit mode that attempts to reproduce old code/settings exactly. It is not required for the first replay-tuning mechanism.

## Point-in-time data rules

Generation inputs must be bounded to `as_of`:
- market bars: `bar_time <= as_of` and, where available, `available_at <= as_of`
- news: `published_at <= as_of` and target `available_at <= as_of`
- context snapshots: latest snapshot with `computed_at <= as_of`
- fundamental snapshots: latest snapshot with `as_of <= replay as_of`
- settings/configs: current non-tuned settings for target tuning mode unless a historical audit mode is explicitly selected

Outcome-resolution inputs are different:
- post-`as_of` bars may be used only to score generated plans
- outcome bars must never affect generation-time signals, context, actionability, or plan framing

## Candidate config override rules

Replay tuning must evaluate candidate plan-generation configs through a scoped override:
- unknown keys are rejected by the registered parameter schema
- the live active config is not mutated
- every replay artifact stores the candidate config hash or config version reference
- equal inputs plus equal config must produce deterministic plan levels

## Resolution rules

Replay-generated plans must resolve through `recommendation-plan-resolution-spec.md` semantics.

Target behavior:
- intraday bars decide final entry/stop/take ordering when available
- daily bars may be used only as prefilter or documented fallback
- same-bar ambiguity is resolved conservatively according to the plan-resolution engine
- replay outcomes are stored separately from live outcomes and keyed by replay/candidate provenance

## Replay eligibility

Eligibility is a quality gate over replayed cases.

Tier A:
- generation inputs are point-in-time bounded
- required signal/context fields are present
- replay plan generation completed
- outcome is resolved with canonical intraday semantics
- provenance is complete

Tier B:
- generation completed but minor non-critical gaps or accepted fallback resolution exist
- allowed for research summaries and manual analysis

Tier C:
- weak, incomplete, or diagnostic-only case
- not allowed for ranking or promotion

Auto-promotion must rely primarily on Tier A replay evidence once replay tuning is implemented.

## Current implementation notes

Implemented today:
- historical market bars support `available_at`
- historical news items support `available_at` with inferred-availability metadata for legacy/provider-limited rows
- historical replay batches/slices exist
- historical replay can hydrate/build market input summaries
- historical replay coverage reports include point-in-time bars, news, context snapshots, and fundamental snapshots
- historical replay slice execution invokes watchlist orchestration for plan generation when that service is configured, passing the slice `as_of`
- replay-generated signal diagnostics and plan evidence/signal payloads receive replay provenance with batch id, slice id, `as_of`, code/settings/input hashes, coverage summary, and input warnings
- replay execution can apply a scoped plan-generation tuning config override from batch config without mutating the live active config, and unknown keys are rejected through the parameter schema
- replay-generated plans are resolved through the canonical evaluation path and stored separately in `replay_plan_outcomes`
- replay-generated plan/outcome cases produce `replay_eligibility_records` with Tier A/B/C/ineligible quality labels, tuning eligibility, rejection reasons, and diagnostics
- plan-generation tuning supports `point_in_time_replay` and `wide_point_in_time_replay` modes that aggregate candidate metrics from existing replay eligibility records, include the baseline candidate, are repeatable for unchanged replay artifacts, and reject stale replay artifacts when code/settings versions no longer match
- ranked replay tuning candidates can be bridged into deterministic historical replay batches carrying scoped candidate config overrides for subsequent plan generation/resolution
- completed per-candidate replay batches can be aggregated back to tuning candidate summaries with eligible counts, Tier A/B/C counts, outcome counts, resolution-source split, and replay-based reranking
- bounded synchronous execution can create/enqueue candidate replay batches and execute their queued slices through the job execution service for research workflows, including an opt-in path from the main tuning `run()` workflow
- plan-generation tuning has compact eligible-record cache and deterministic candidate scoring
- initial replay coverage reporting quantifies readiness before replay-driven tuning

Not implemented yet:
- full production gate policy for unattended auto-promotion beyond the current replay Tier A and execution-required fail-closed gates
- full replay artifact reuse across per-candidate slice execution, beyond the current replay eligibility aggregation keys
- auto-promotion based on replay Tier A evidence
