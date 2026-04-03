# Plan generation tuning implementation plan

**Status:** implementation plan derived from `plan-generation-tuning-spec.md`

This document translates the spec into concrete codebase decisions.

It is the execution plan to follow before and during implementation.

## Implementation progress note

Current repository state now includes:
- retirement of the old weight-optimization job type from active app workflows
- new plan-generation tuning persistence models, repositories, routes, and service layer
- active plan-generation config loading in `watchlist_orchestration.py`
- immutable spec-driven tests in `tests/test_plan_generation_tuning.py`
- updated worker/job execution wiring for `plan_generation_tuning`
- frontend routing and a first operational plan-generation tuning research page

## Executive decision

### Decision: replace, do not extend, the legacy weight optimizer

After inspection, the existing weight-optimization flow is **not** an appropriate base for autonomous plan-generation tuning.

## Why the legacy optimizer should not be reused as the main implementation

Inspected components:
- `src/trade_proposer_app/services/optimizations.py`
- `src/trade_proposer_app/services/job_execution.py`
- `tests/test_optimizations.py`
- `src/trade_proposer_app/services/proposals.py`
- `src/trade_proposer_app/services/watchlist_orchestration.py`

### What the legacy optimizer does today

The current `WeightOptimizationService`:
- counts aggregate resolved wins and losses
- computes a single `delta_ratio`
- scales selected values inside `weights.json`
- writes the updated file back to disk
- creates filesystem backups for rollback
- runs as `JobType.WEIGHT_OPTIMIZATION`

### Why it is insufficient

It does **not** provide:
- plan-generation-specific parameter schema
- versioned candidate configs
- candidate ranking
- deterministic backtest replay by candidate
- holdout validation
- per-candidate promotion eligibility
- autonomous daily exploration with guardrails
- active config provenance in the database
- plan-generation-specific audit history

### Important architectural mismatch

The legacy optimizer mutates:
- `src/trade_proposer_app/data/weights.json`

That file is used by proposal scoring in:
- `src/trade_proposer_app/services/proposals.py`
- parts of `ticker_deep_analysis.py`

But the current **live recommendation-plan construction** that sets:
- actionable / no-action decisions
- entry price range
- stop loss
- take profit

is centered in:
- `src/trade_proposer_app/services/watchlist_orchestration.py`

Specifically, the actionable plan path calls:
- `_family_adjusted_trade_levels(...)`
- `_calibration_review(...)`
- shortlist / threshold / transmission logic
- setup-family-specific plan construction

So the old optimizer acts on an upstream scoring file, while the new feature must tune the downstream plan-generation and trade-level logic.

## Concrete architectural conclusion

### Remove the old optimizer completely

Because the legacy weight-optimization job has never been used, it should be removed outright.

Remove:
- `JobType.WEIGHT_OPTIMIZATION`
- `WeightOptimizationService`
- weight-optimization branches in `job_execution.py`
- scheduler and active-run guards specific to the old job
- old optimization settings that only existed for that job
- frontend labels and controls for weight optimization
- tests and docs that describe the old job as a supported workflow

Do **not** preserve:
- old runs
- backward compatibility
- migration logic for old optimizer state

Important distinction:
- keep `weights.json` only if live proposal/deep-analysis scoring still reads it
- remove only the obsolete job that mutates it

### Build a new dedicated subsystem

Create a dedicated plan-generation tuning subsystem with:
- its own tables
- its own repositories
- its own service layer
- its own API routes
- its own UI pages
- its own job type
- its own active config lifecycle

## Real code boundaries for the new feature

## 1. Live plan-generation integration point

Primary live-consumption path:
- `src/trade_proposer_app/services/watchlist_orchestration.py`

This is where the active plan-generation config must be read and applied.

### Phase-1 integration targets inside watchlist orchestration

Initial implementation should integrate active config into logic that determines:
- actionable threshold adjustments
- family-specific entry offsets
- family-specific stop-loss multipliers
- family-specific take-profit / reward multipliers
- context/transmission modifiers that alter those price levels or selectivity
- degraded-data penalties that alter actionability or price aggressiveness

### Specific code areas already relevant

Observed relevant hooks include:
- `_calibration_review(...)`
- `_minimum_shortlist_confidence(...)`
- `_minimum_shortlist_attention(...)`
- action selection logic before actionable plan creation
- `_family_adjusted_trade_levels(...)`
- `_risk_reward_ratio(...)`

## 2. Historical scoring inputs

The new tuning engine should use:
- `RecommendationPlan`
- `RecommendationPlanOutcome`
- `RecommendationDecisionSample`
- linked ticker signal / context snapshots where needed

These already exist and provide the right historical anchor.

## 3. Job execution integration

The project already has worker-backed job execution through:
- `src/trade_proposer_app/services/job_execution.py`

Plan-generation tuning should integrate into this model.

## Required job-type addition

Add a new enum value to `JobType`:
- `PLAN_GENERATION_TUNING = "plan_generation_tuning"`

Do **not** reuse `WEIGHT_OPTIMIZATION`.

## Concrete implementation design

## A. Persistence model

Add the following persistence models and matching repositories.

### 1. `PlanGenerationTuningRunRecord`
Table: `plan_generation_tuning_runs`

Purpose:
- one record per tuning execution

Fields:
- `id`
- `status`
- `mode`
- `objective_name`
- `promotion_mode`
- `baseline_config_version_id`
- `winning_candidate_id`
- `promoted_config_version_id`
- `eligible_record_count`
- `eligible_tier_a_count`
- `validation_record_count`
- `candidate_count`
- `summary_json`
- `filters_json`
- `error_message`
- `code_version`
- timestamps

### 2. `PlanGenerationTuningCandidateRecord`
Table: `plan_generation_tuning_candidates`

Purpose:
- one row per candidate in a run

Fields:
- `id`
- `run_id`
- `rank`
- `status`
- `is_baseline`
- `promotion_eligible`
- `config_json`
- `changed_keys_json`
- `score_summary_json`
- `metric_breakdown_json`
- `sample_breakdown_json`
- `validation_summary_json`
- `rejection_reasons_json`
- timestamps

### 3. `PlanGenerationTuningConfigVersionRecord`
Table: `plan_generation_tuning_config_versions`

Purpose:
- versioned historical configs

Fields:
- `id`
- `version_label`
- `status`
- `source`
- `parent_config_version_id`
- `source_run_id`
- `source_candidate_id`
- `config_json`
- `parameter_schema_version`
- timestamps

### 4. `PlanGenerationTuningEventRecord`
Table: `plan_generation_tuning_events`

Purpose:
- immutable audit trail

Fields:
- `id`
- `event_type`
- `run_id`
- `config_version_id`
- `candidate_id`
- `actor_type`
- `actor_identifier`
- `payload_json`
- timestamps

### 5. Active config pointer

Implement one of these:

Preferred:
- a dedicated app setting key such as `plan_generation_active_config_version_id`

Alternative:
- a singleton active-config record

Decision:
- use a settings key first, because the app already has `AppSettingRecord` and `SettingsRepository`
- still keep full config versions in dedicated tables

## B. Domain models

Add domain models for:
- `PlanGenerationTuningRun`
- `PlanGenerationTuningCandidate`
- `PlanGenerationTuningConfigVersion`
- `PlanGenerationTuningEvent`
- `PlanGenerationTuningParameterDefinition`
- `PlanGenerationTuningState`

## C. Parameter schema

Implement a first-class parameter registry in code.

### Location

Recommended new module:
- `src/trade_proposer_app/services/plan_generation_tuning_parameters.py`

### Phase-1 parameter families

The first implementation should keep the parameter set bounded and tied to current live code.

Initial parameter groups:

#### 1. Selectivity / actionability
- `global.actionable_threshold_offset`
- `global.degraded_action_penalty`
- `global.transmission_headwind_penalty`
- `global.transmission_tailwind_bonus`
- `global.contradiction_penalty_per_hit`

#### 2. Entry shaping
- `global.entry_offset_atr_multiplier`
- `setup_family.breakout.entry_offset_atr_multiplier`
- `setup_family.continuation.entry_offset_atr_multiplier`
- `setup_family.mean_reversion.entry_offset_atr_multiplier`

#### 3. Stop-loss shaping
- `global.stop_loss_atr_multiplier`
- `setup_family.breakout.stop_loss_atr_multiplier`
- `setup_family.continuation.stop_loss_atr_multiplier`
- `setup_family.mean_reversion.stop_loss_atr_multiplier`

#### 4. Take-profit shaping
- `global.take_profit_reward_multiplier`
- `setup_family.breakout.take_profit_reward_multiplier`
- `setup_family.continuation.take_profit_reward_multiplier`
- `setup_family.mean_reversion.take_profit_reward_multiplier`

#### 5. Confidence / context modifiers that affect live plans
- `global.context_strength_bonus_scale`
- `global.event_relevance_bonus_scale`
- `global.freshness_bonus`
- `global.fading_penalty`

### Why this bounded set

These parameters map directly onto current code behavior and can be wired into live plan generation without inventing a new architecture first.

They also match the spec goal: tune what participates in entry, stop loss, take profit, and meaningful actionability decisions.

## D. Active config loading path

Add settings repository support for:
- reading the active plan-generation config version id
- resolving the active config JSON

Recommended methods on `SettingsRepository`:
- `get_plan_generation_active_config_version_id() -> int | None`
- `set_plan_generation_active_config_version_id(config_version_id: int) -> AppSetting`
- `get_plan_generation_tuning_settings() -> dict[str, object]`
- `set_plan_generation_tuning_settings(...) -> dict[str, object]`

Add a dedicated repository for config versions to load the effective config.

## E. Live orchestration changes

### Required new helper

In `watchlist_orchestration.py`, add a loader-normalizer such as:
- `_normalize_plan_generation_tuning_config(...)`
- `_plan_generation_tuning_value(key, default, scope=...)`

### Required live behavior

The service must apply the active config when generating actionable plans.

This should be done in a way that:
- if no active config exists, behavior remains baseline-compatible
- if a config exists, only registered parameters are read
- invalid or missing config fields fall back safely to defaults

### Phase-1 implementation rule

Do not refactor the entire orchestration service first.

Instead:
- isolate existing thresholds and ATR-/reward-style constants behind helper methods
- make those helpers consume the active tuning config
- preserve old behavior when config values are defaulted

This keeps risk low and makes candidate replay measurable.

## F. Replay / evaluation engine

Add a dedicated service:
- `src/trade_proposer_app/services/plan_generation_tuning.py`

### Responsibilities

- load active baseline config
- load parameter registry
- load eligible historical records
- partition records into search and holdout slices
- generate bounded candidates
- replay candidate behavior on historical examples
- compute candidate metrics
- rank candidates lexicographically
- mark promotion eligibility
- optionally promote the winner
- persist run/candidate/config/event records

### Important implementation constraint

The replay engine should **not** depend on live network calls.

It must work from stored records and reconstructable data only.

### Replay strategy for phase 1

Because full historical reconstruction can be expensive, use a staged strategy:

#### Phase 1A
Use stored plan, outcome, decision-sample, and signal/context payloads to reconstruct enough features to rescore plan-generation decisions deterministically.

#### Phase 1B
Where feasible, refactor the live plan-generation computations into pure helper functions reusable by both:
- live orchestration
- tuning replay

This is the preferred end state.

## G. Candidate generation

### Automatic mode
Generate candidates from:
- live baseline
- small local perturbations around top-impact parameters
- last promoted winners
- last strong non-promoted candidates

Constraints:
- max 50 candidates
- max 5 changed parameters per candidate
- max 2 steps from baseline per changed parameter

### Manual mode
Allow a wider bounded search:
- up to 200 candidates

## H. Ranking implementation

Implement the lexicographic ranking from the spec directly, not as an opaque blended score.

Recommended comparison function order:
1. hard validity
2. actionable win rate
3. actionable win count
4. actionable expected value
5. closeness to active config
6. fewer changed keys

Persist both:
- raw metric values
- comparison summary used for final rank

## I. Scheduler and automation

### New settings keys

Add app settings for automation state, for example:
- `plan_generation_tuning_auto_enabled`
- `plan_generation_tuning_auto_promote_enabled`
- `plan_generation_tuning_schedule_cron`
- `plan_generation_tuning_max_candidates_auto`
- `plan_generation_tuning_min_actionable_resolved`
- `plan_generation_tuning_min_tier_a_records`

### Scheduling behavior

Integrate with the existing worker/scheduler flow.

At most one active plan-generation tuning run at a time.

## J. API routes

Add a new route module:
- `src/trade_proposer_app/api/routes/plan_generation_tuning.py`

Implement:
- `GET /api/plan-generation-tuning`
- `GET /api/plan-generation-tuning/runs`
- `GET /api/plan-generation-tuning/runs/{run_id}`
- `POST /api/plan-generation-tuning/run`
- `GET /api/plan-generation-tuning/configs`
- `GET /api/plan-generation-tuning/configs/{config_version_id}`
- `POST /api/plan-generation-tuning/configs/{config_version_id}/promote`
- `POST /api/plan-generation-tuning/configs/{config_version_id}/rollback`
- `GET /api/plan-generation-tuning/parameters`
- `POST /api/plan-generation-tuning/settings`

Use paginated responses for list endpoints.

## K. Frontend plan

### Routing

Replace the current redirect route in `frontend/src/App.tsx`:
- `research/plan-generation-tuning`

with real pages.

### Required first pages

1. `plan-generation-tuning-page.tsx`
   - active config summary
   - latest run summary
   - auto-mode state
   - links to runs and configs

2. `plan-generation-tuning-runs-page.tsx`
   - paginated runs

3. `plan-generation-tuning-run-detail-page.tsx`
   - candidate ranking
   - baseline vs winner
   - guardrail outcomes

4. `plan-generation-tuning-configs-page.tsx`
   - config history
   - active marker
   - rollback action

### Navigation updates

Update research navigation so plan-generation tuning is a first-class page, not a placeholder.

## L. Legacy removal decision

### Immediate behavior

- remove weight optimization entirely
- do not preserve old job runs or compatibility behavior
- do not redirect old job flows to the new subsystem
- keep `weights.json` only where live scoring still requires it

### Operator-facing outcome

After this change, the app should expose only the new tuning concepts in this area:
- `Signal gating tuning` → recall tuning
- `Plan generation tuning` → candidate-based precision tuning for actionable plans

No operator-facing `Weight optimization` workflow should remain.

## M. Proposed migration set

### Alembic migration 1
Create new tables:
- `plan_generation_tuning_runs`
- `plan_generation_tuning_candidates`
- `plan_generation_tuning_config_versions`
- `plan_generation_tuning_events`

### Alembic migration 2
Seed settings defaults for:
- active config pointer
- automation controls
- minimum thresholds

### Alembic migration 3
Remove any obsolete persisted settings or schema artifacts that only supported weight optimization, if present in the current database.

## N. Acceptance path by milestone

### Milestone 1: backend foundations
- tables and models exist
- parameter registry exists
- active config version exists
- manual dry run works
- run detail and config history APIs work

### Milestone 2: live config consumption
- watchlist orchestration reads active plan-generation config
- default config preserves baseline behavior
- promoted config changes live plan generation deterministically

### Milestone 3: autonomous mode
- scheduled daily runs work
- holdout validation works
- auto-promotion respects guardrails
- rollback works

### Milestone 4: frontend workflow
- research pages exist
- run/config inspection is usable
- operators can inspect promotion decisions and rollback history

## O. Recommended coding order

1. remove the old weight-optimization job, settings, tests, docs, and UI exposure
2. add new job type and persistence models
3. add repositories and domain models
4. add parameter registry
5. add active-config settings and config-version repository
6. refactor `watchlist_orchestration.py` to read normalized plan-generation config defaults
7. expose manual state and dry-run endpoints
8. implement candidate replay and ranking
9. implement promotion + rollback
10. wire scheduled automation
11. add frontend pages
12. finalize docs for the new tuning-only workflow

## P. Explicit implementation guardrail

Autonomous implementation should not attempt to optimize every numerical constant in the planner on the first pass.

It should start with the bounded parameter families above, because they are:
- meaningful
- inspectable
- replayable
- tied directly to entry/stop/take-profit and actionability

Once the bounded system is working, the parameter registry can be expanded in later iterations.
