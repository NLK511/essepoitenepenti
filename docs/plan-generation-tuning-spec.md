# Plan generation tuning spec

**Status:** authoritative implementation spec

This document defines the required behavior for autonomous plan-generation tuning.

Use it as the binding reference when implementing services, schema, jobs, APIs, UI, scheduling, and promotion behavior for recommendation-plan generation tuning.

If implementation conflicts with this document, this document wins unless it is explicitly amended.

## Read this spec in two layers

This document serves two purposes at once:

1. **current shipped phase-1 behavior**
2. **authoritative target behavior** for the fuller autonomous tuning system

When reading this spec, interpret it as follows:
- sections that describe current UI pages, routes, persistence, and bounded candidate ranking reflect shipped behavior
- sections that define stricter autonomous guardrails, promotion policy, and broader governance remain the required target unless and until implementation catches up

## Current shipped phase-1 snapshot

The app currently ships a **phase-1 bounded implementation** of plan-generation tuning.

What is live now:
- dedicated plan-generation tuning routes, persistence, runs, candidates, and config versions
- a real research page for inspecting runs, grouped candidate experiments, per-campaign results, config promotion, and the ranked exploration campaign plan
- settings for active config selection and stored automation readiness flags
- bounded parameter-schema-driven candidate generation
- deterministic candidate ranking centered on win rate, then win count, then expected value
- guarded manual run/apply behavior in the backend
- live consumption of the active config during plan construction

What is not yet fully implemented to the target standard in this spec:
- the full autonomous daily evolution workflow
- the full stricter promotion guardrail set described later in this document
- all target diversity, concentration, and stability protections
- complete enforcement of the eventual autonomous promotion thresholds as the sole runtime policy

### Interpretation of auto settings in the current build

`auto_enabled` and `auto_promote_enabled` should currently be read as **stored readiness/configuration flags**.

They express intended future autonomous behavior, but they should not be read as proof that the complete autonomous scheduler/promotion policy described later in this spec is already fully active.

## Purpose

The goal of plan-generation tuning is to improve the quality of **actionable recommendation plans** after signals have already passed upstream gating.

This means plan-generation tuning is no longer the only optimization surface, and it should not be read that way. It sits between upstream shortlist control and downstream trust validation:
- **signal gating tuning** controls what reaches serious consideration
- **plan generation tuning** controls how candidate trades are framed once they are in scope
- **recommendation-quality review and walk-forward validation** control whether those changes are trustworthy enough to keep or promote

This tuning layer is responsible for improving the quality of:
- entry price selection
- stop-loss selection
- take-profit selection
- supporting confidence / threshold / weighting logic that materially affects whether a plan becomes actionable and how its prices are formed

This is a **precision-oriented** optimization surface.

Signal gating tuning remains a separate **recall-oriented** surface.

## Product intent

The system must support two modes:

1. **Manual research mode**
   - operators can inspect historical tuning runs, compare candidates, and manually promote or reject candidates

2. **Automatic evolution mode**
   - the app can run scheduled plan-generation tuning daily, evaluate new candidate settings on historical data, and automatically promote a winning candidate only when strict safety rules pass

Automatic mode must be conservative.
It exists to improve the live configuration gradually, not to chase noise.

## Hard scope boundary

This feature is about **plan generation**, not general optimization.

It covers parameters that materially affect:
- whether a generated proposal is actionable versus non-actionable
- the exact entry, stop-loss, and take-profit values
- plan-side context interpretation that influences those prices or their confidence
- feature-weight interactions used to derive those values

It does **not** cover:
- market data ingestion changes
- outcome-resolution semantics
- execution engine changes beyond using the promoted plan-generation config
- broad gating-threshold tuning already owned by signal-gating tuning
- unrelated repository-wide weight optimization without direct plan-generation impact

## Canonical objective order

Candidates must be ranked using the following ordered objective:

1. **maximize actionable win rate**
2. **maximize actionable win count**
3. **maximize actionable expected value**

This ordering is strict.

Implementation must not collapse the three into an arbitrary single weighted score unless that score preserves this ordering as a lexicographic decision rule.

### Required interpretation

- A candidate with materially lower actionable win rate must not outrank one with higher actionable win rate just because it produces more trades.
- If two candidates are effectively tied on win rate, prefer the one with higher actionable win count.
- If both are effectively tied on win rate and win count, prefer the one with better expected value.

### Required tie handling

The implementation must define explicit tie tolerances to avoid unstable rank flips from tiny numeric differences.

Initial required tolerances:
- win-rate tie tolerance: `0.25 percentage points`
- win-count tie tolerance: `1 win`
- expected-value tie tolerance: `0.02R` or equivalent normalized return unit

If a different return unit is used, the equivalent tolerance must be documented in the implementation.

## Relationship to existing tuning systems

### Signal gating tuning

Signal gating tuning is separate and must remain separate.

- signal gating tuning optimizes upstream selection / recall
- plan generation tuning optimizes downstream plan quality / precision
- recommendation-quality review and walk-forward validation judge whether tuning changes deserve trust or promotion

The two systems may share infrastructure patterns, but they must not share the same active configuration object or promotion policy.

Practical division of labor:
- use **signal gating tuning** when the shortlist is too strict, too loose, or mishandles degraded near-misses
- use **plan generation tuning** when the system is already surfacing candidates but entry/stop/take-profit framing or actionable precision needs improvement
- use **quality-summary, calibration, baseline, evidence, and walk-forward surfaces** to decide whether any tuning change should actually influence live behavior

### Legacy weight optimization

The old weight-optimization job is **retired**.

Implementation rule:
- do **not** revive or extend the legacy optimizer in-place
- do **not** preserve compatibility for its job type, settings, or rollback workflow
- keep `weights.json` only as a normal scoring input where live proposal/deep-analysis code still needs it

Required implementation assumption:
- use a **new dedicated plan-generation tuning framework**
- reuse only generic helper patterns, not the legacy optimizer workflow or data model

## Canonical tuning surface

The tuning surface includes any parameter that materially contributes to:
- entry derivation
- stop-loss derivation
- take-profit derivation
- actionable/non-actionable plan transition
- confidence or selectivity adjustments that materially affect the final actionable set
- technical-indicator influence on price placement or confidence
- context or regime influence on price placement or confidence
- setup-family-specific pricing rules

### Examples of admissible parameters

These are in scope if they exist in the implementation:
- ATR-based stop multipliers
- risk-reward target multipliers
- setup-family-specific entry offsets
- breakout / pullback thresholds
- technical-indicator weights used in confidence or price framing
- context-bias adjustments that alter target/stop spacing
- degraded-data penalties that alter plan selectivity or price aggressiveness
- regime-specific overrides
- family-specific confidence floors for actionable status

### Examples of inadmissible parameters

These are not in scope unless they directly alter plan generation:
- API polling intervals
- data vendor selection
- watchlist seed definitions
- unrelated UI defaults
- general-purpose model settings not tied to plan generation

## Guiding design principle

The tuning system must tune the **full plan-generation scoring and price-construction pipeline**, but via a **structured parameter schema**.

That means:
- do not hardcode a few special-case knobs and call the system complete
- do not allow arbitrary unbounded JSON mutation either
- represent the tunable surface with named parameters, types, ranges, defaults, and optional family/regime scopes

## Required parameter schema

Every tunable parameter must be described by metadata that includes:
- `key`
- `label`
- `type` (`float`, `int`, `bool`, `enum`)
- `scope` (`global`, `setup_family`, `regime`, `direction`, or a combination if needed)
- `default_value`
- `current_live_value`
- `min_value` / `max_value` or enum options
- `step` for numeric exploration
- `exploration_mode` (`grid`, `mutation`, `baseline_only`, `fixed`)
- `materiality_class` (`critical`, `secondary`, `experimental`)
- `description`

Implementation must reject candidate configs containing keys not present in the registered parameter schema.

## Data usage policy

The system should use **all data that can meaningfully be used**, but only after severe eligibility checks.

The tuning system must be deliberately strict about what counts as evaluable evidence.

## Canonical data sources

The tuning engine may use:
- `RecommendationPlan`
- `RecommendationPlanOutcome`
- `RecommendationDecisionSample`
- context snapshots linked to plan generation
- ticker-signal snapshots linked to plan generation
- any derived replay/backtest artifacts that reproduce plan-generation inputs without leakage

## Data eligibility rules

A record is eligible only if all required conditions hold.

### Required minimum eligibility

A candidate evaluation record must have:
- reproducible plan-generation inputs, or enough stored artifacts to reconstruct the relevant plan-generation features
- a known plan-generation timestamp
- a known directional/actionable interpretation
- a resolved or otherwise scoreable outcome if it is being used for win/loss or expected-value scoring. This includes real `win`/`loss` outcomes as well as `phantom_win` and `phantom_loss` records from `no_action` or `watchlist` plans with an `intended_action`.
- broker-resolved positions may also qualify when a broker outcome is present and the outcome can be scored from stored realized-return data even if simulation excursion fields are absent

### Required exclusions

The implementation must exclude records when:
- outcome is unresolved for a metric that requires resolution
- required feature payloads are missing or corrupted
- a plan cannot be reconstructed with confidence
- there is known leakage from future data into the inputs
- the record belongs to a backfill or recompute path that does not preserve original generation semantics and is not explicitly marked replay-safe

### Recommended inclusion tiers

The engine should classify records into tiers:
- **Tier A**: fully reproducible, resolved, high-confidence records; safe for ranking and promotion decisions
- **Tier B**: mostly reproducible records with minor non-critical gaps; safe for research summaries, not sufficient alone for auto-promotion
- **Tier C**: incomplete or weakly reproducible records; visible for diagnostics only, excluded from promotion scoring

Automatic promotion must rely primarily on Tier A data.

## Anti-leakage rules

The implementation must prevent using future knowledge.

Required rules:
- candidate scoring must only use information available at plan-generation time plus later outcome labels for evaluation
- no feature field may be populated from outcome-period bars or post-generation derived metrics unless explicitly marked evaluation-only
- calibration baselines and thresholds used inside a replay must be sourced from the candidate config and admissible historical context only
- if time-split evaluation is implemented, training windows must end strictly before validation windows

## Backtesting methodology

The tuning engine must backtest candidates against historical records using deterministic replay rules.

### Required replay behavior

For each eligible record, candidate evaluation must attempt to answer:
- would this candidate have produced an actionable plan?
- if actionable, what entry/stop/take-profit would it have produced?
- if those prices differ from the stored live plan, what would the resulting outcome have been under canonical resolution semantics?
- if non-actionable, what opportunity was intentionally filtered out?

### Resolution reference

Outcome comparison must use the canonical rules in:
- `recommendation-plan-resolution-spec.md`
- `archive/implementation-plans/recommendation-plan-evaluation-recompute-notes.md`

Plan-generation tuning must not invent a separate outcome semantics.

### Determinism requirement

Given the same candidate config, same eligible dataset, and same baseline code version, the tuning run must produce the same ranking result.

Any stochastic exploration algorithm must still persist the random seed and full candidate list so the run is replayable.

## Candidate generation rules

The system must support ranked candidate generation while remaining inspectable.

### Phase 1 required generation strategy

The first implementation must generate candidates from:
- current live baseline config
- small local perturbations around the baseline
- top historical promoted configs
- top historical non-promoted but high-scoring configs
- optional bounded mutations within parameter limits

### Exploration and backtest workflow

Manual research runs should support a broader exploration mode that is deterministic and replayable.

Required exploration behavior:
- evaluate the largest eligible replay-safe dataset available to the run
- use rolling walk-forward validation over the eligible history, not just a single train/validation split
- persist the exploration seed, candidate list, and full candidate metrics for replayability
- include at least one baseline candidate, local perturbations, historical configs, and bounded random mutations when the exploration mode is enabled
- keep the search bounded; exploration must remain auditable and capped
- prefer the oldest eligible records for search/fit summaries only when a time split is required; validation must remain holdout-based
- include broker-resolved records and phantom scoreable records in the eligible exploration set when they satisfy the replay rules above

### First campaign exploration envelope

The initial manual exploration campaign must stay inside the following exact parameter ranges. These ranges are narrower than the full schema limits and are meant to focus the search near plausible profit/risk trade-offs before widening the search space.

| Parameter key | Exploration min | Exploration max |
| --- | ---: | ---: |
| `global.entry_band_risk_fraction` | `0.00` | `0.25` |
| `global.headwind_stop_multiplier` | `0.84` | `1.02` |
| `setup_family.breakout.stop_distance_multiplier` | `0.65` | `1.05` |
| `setup_family.breakout.take_profit_distance_multiplier` | `0.95` | `1.45` |
| `setup_family.mean_reversion.stop_distance_multiplier` | `0.88` | `1.32` |
| `setup_family.mean_reversion.take_profit_distance_multiplier` | `0.72` | `1.08` |
| `setup_family.catalyst_follow_through.take_profit_distance_multiplier` | `1.05` | `1.50` |
| `setup_family.macro_beneficiary_loser.take_profit_distance_multiplier` | `1.00` | `1.30` |

Bounded random mutations and step-based local perturbations in exploration mode must be clamped to this envelope.
The exploration generator should also broaden its candidate diversity with deeper local steps and additional bounded random mutations, while still staying capped and replayable.

### Ranked exploration campaign plan

The first exploration campaign should allocate effort in this order:

| Priority | Campaign | Primary knobs | Candidate budget |
| --- | --- | --- | ---: |
| 1 | Entry calibration | `global.entry_band_risk_fraction` | `16` |
| 2 | Risk protection | `global.headwind_stop_multiplier`, `setup_family.breakout.stop_distance_multiplier`, `setup_family.mean_reversion.stop_distance_multiplier` | `32` |
| 3 | Reward expansion | `setup_family.breakout.take_profit_distance_multiplier`, `setup_family.mean_reversion.take_profit_distance_multiplier`, `setup_family.catalyst_follow_through.take_profit_distance_multiplier`, `setup_family.macro_beneficiary_loser.take_profit_distance_multiplier` | `48` |
| 4 | Historical reuse | Re-test promoted and high-scoring historical configs | `24` |
| 5 | Bounded random mutation | Deterministic local mutations across the full schema | `24` |

This yields a default exploration budget of `144` candidates per run before deduplication.

### Candidate generation constraints

### Candidate generation constraints

- candidate count per run must be explicitly capped
- every candidate must be fully materialized and stored before evaluation finishes
- candidates must declare which parameters differ from the baseline
- large multi-dimensional blind searches are not allowed in the initial implementation

### Initial default limits

Unless explicitly overridden by config:
- max candidates per scheduled automatic run: `50`
- max candidates per manual research run: `200`
- max changed parameters per candidate in automatic mode: `5`
- max absolute step distance from live baseline in automatic mode: parameter-specific, but default `2 steps`

## Candidate scoring outputs

Each candidate result must persist at least:
- candidate rank
- candidate config
- baseline delta summary
- actionable count
- actionable resolved count
- actionable win count
- actionable loss count
- actionable win rate
- actionable expected value
- total filtered-out count
- coverage rate relative to eligible records
- setup-family breakdown
- direction breakdown
- regime breakdown if available
- sample-size flags
- promotion eligibility flag
- rejection reasons

## Candidate ranking rules

Ranking must be lexicographic with guardrails.

### Ranking algorithm

1. exclude candidates that fail hard validity rules
2. compare remaining candidates by actionable win rate
3. if tied within tolerance, compare actionable win count
4. if tied within tolerance, compare actionable expected value
5. if still tied, prefer the candidate closer to the current live config
6. if still tied, prefer the candidate with fewer changed parameters

### Hard validity rules

A candidate must be marked invalid for auto-promotion if any of the following holds:
- actionable resolved count is below the minimum threshold
- effective sample quality is below the required threshold
- candidate creates impossible or invalid price structures
- candidate materially degrades a protected secondary metric beyond allowed limits
- candidate depends on parameters outside the registered schema

## Minimum sample requirements

The system must not auto-promote on tiny samples.

Initial required thresholds for auto-promotion:
- minimum actionable resolved plans: `50`
- minimum wins: `20`
- minimum eligible Tier A records: `200`
- minimum distinct tuning dates: `20 market days`
- minimum distinct tickers: `20`

These thresholds may be tightened later, but implementation must not go below them without an explicit spec update.

Manual research runs may show lower-sample candidates, but those candidates must be visibly marked as not auto-promotable.

## Protected secondary metrics

Although ranking is driven by the canonical objective order, the following metrics must be treated as protection constraints:
- actionable count collapse
- expected value collapse
- extreme concentration in one ticker or one setup family
- excessive degradation in a major setup family
- excessive reliance on degraded-input plans
- large instability across recent time windows

### Required default protection rules for auto-promotion

A candidate must not auto-promote if it causes any of the following relative to the current live baseline on the same eligible sample:
- actionable count drops by more than `40%`
- actionable resolved count drops by more than `35%`
- expected value drops by more than `0.10R`
- any major setup family with at least `20` resolved actionable records loses more than `15 percentage points` of win rate
- top-1 ticker concentration among actionable plans exceeds `25%` unless the baseline already exceeds it and the candidate improves the concentration

These are safety guardrails, not ranking objectives.

## Acceptance threshold for auto-promotion

Automatic promotion must require a meaningful improvement over the current live baseline.

Initial required minimum improvement:
- actionable win rate must improve by at least `1.0 percentage point`
- or by at least `0.5 percentage points` if the candidate also increases actionable win count by at least `10%`

If those conditions are not met, the candidate may still be stored and ranked, but it must not auto-promote.

## Time-split evaluation requirement

To reduce overfitting, every auto-promotion decision must be based on at least two views:
- **full eligible backtest view**
- **recent holdout or rolling-window validation view**

A candidate must pass both.

### Initial required holdout behavior

At minimum, the implementation must reserve the most recent eligible slice as a holdout validation window.

Default rule:
- oldest `80%` of eligible Tier A records for candidate search / score aggregation
- most recent `20%` for validation gating

If record counts are too small, the run must fall back to research-only and disable auto-promotion.

## Promotion policy

Promotion means making a candidate the live plan-generation configuration used by future plan generation.

### Modes

The system must support:
- `dry_run`
- `manual_promote`
- `auto_promote`
- `rollback`

### Promotion requirements

A candidate may be promoted only if:
- it is rank 1 under the canonical ranking rules
- it passes hard validity rules
- it passes sample-size thresholds
- it passes holdout validation
- it passes protected secondary metric guardrails
- it exceeds the minimum improvement threshold
- a full audit trail is persisted

### Rollback requirements

The system must support rollback to the previous live config.

Rollback must persist:
- source promoted config version
- reverted-to config version
- reason
- actor or system mode
- timestamp

## Daily automatic evolution mode

The system must support a scheduled daily run.

### Required schedule behavior

- at most one active scheduled plan-generation tuning run at a time
- if a prior run is still active, skip the next scheduled run and record a skipped event
- automatic mode must default to `dry_run` until explicit enablement is configured
- auto-promotion must be independently toggleable from automatic scheduled evaluation

### Daily run responsibilities

Each scheduled run must:
1. load the active live config
2. load eligible historical data
3. generate bounded candidates
4. evaluate and rank candidates
5. validate the winner against holdout rules
6. auto-promote only if all requirements pass
7. persist a complete run summary and candidate list
8. update the active state endpoint and UI history

## Required persistence model

The implementation must store first-class tuning entities.

A single JSON blob is not sufficient for the full system.

### Required entities

At minimum, create dedicated persistence for:
- `plan_generation_tuning_runs`
- `plan_generation_tuning_candidates`
- `plan_generation_tuning_config_versions`
- `plan_generation_tuning_events`

Optional additional entities are allowed if they simplify implementation.

### Required table semantics

#### `plan_generation_tuning_runs`
One row per tuning execution.

Must include at least:
- `id`
- `status`
- `mode` (`manual`, `scheduled`)
- `objective_name`
- `promotion_mode` (`dry_run`, `manual_promote`, `auto_promote`, `rollback_only`)
- `started_at`
- `completed_at`
- `failed_at`
- `baseline_config_version_id`
- `winning_candidate_id`
- `promoted_config_version_id`
- `eligible_record_count`
- `eligible_tier_a_count`
- `candidate_count`
- `validation_record_count`
- `summary_json`
- `filters_json`
- `error_message`
- `code_version`

#### `plan_generation_tuning_candidates`
One row per evaluated candidate within a run.

Must include at least:
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
- `created_at`

#### `plan_generation_tuning_config_versions`
One row per versioned config available for live use or historical comparison.

Must include at least:
- `id`
- `version_label`
- `status` (`draft`, `active`, `superseded`, `rolled_back`, `rejected`)
- `source` (`seed`, `manual`, `scheduled`, `promoted_candidate`, `rollback`)
- `parent_config_version_id`
- `source_run_id`
- `source_candidate_id`
- `config_json`
- `parameter_schema_version`
- `created_at`
- `activated_at`
- `deactivated_at`

#### `plan_generation_tuning_events`
Immutable audit log for operational changes.

Must include at least:
- `id`
- `event_type`
- `run_id`
- `config_version_id`
- `candidate_id`
- `actor_type` (`system`, `user`)
- `actor_identifier`
- `payload_json`
- `created_at`

## Settings and active live config

The system must expose the currently active live plan-generation tuning config separately from historical versions.

Required behavior:
- active config must be readable without scanning the entire version history
- promotion must atomically switch the active config reference
- live plan generation must read from the active plan-generation config only
- if no dedicated active-config pointer exists yet, one must be added

## API requirements

The backend must provide explicit plan-generation tuning endpoints.

### Required endpoints

- `GET /api/plan-generation-tuning`
  - returns active config, latest run summary, scheduler state, and automatic-mode state

- `GET /api/plan-generation-tuning/runs`
  - paginated list of runs

- `GET /api/plan-generation-tuning/runs/{run_id}`
  - full run detail, including candidate summary list

- `POST /api/plan-generation-tuning/run`
  - manually start a run
  - supports `dry_run` and `manual_promote`

- `POST /api/plan-generation-tuning/configs/{config_version_id}/promote`
  - manually promote a previously evaluated config version

- `POST /api/plan-generation-tuning/configs/{config_version_id}/rollback`
  - rollback to a prior config version if allowed by policy

- `GET /api/plan-generation-tuning/configs`
  - paginated list of config versions

- `GET /api/plan-generation-tuning/configs/{config_version_id}`
  - config detail with provenance

- `GET /api/plan-generation-tuning/parameters`
  - registered tunable parameter schema

- `POST /api/plan-generation-tuning/settings`
  - update scheduler and automatic-mode settings, not the candidate config itself

### Optional endpoints

These are allowed but not required initially:
- candidate-detail endpoint
- comparison endpoint for two configs
- endpoint for skipped scheduled-run history

## API response requirements

Responses must be stable and explicit.

Required principles:
- paginated endpoints return `{ items, total, limit, offset }`
- run-detail responses include both baseline and winner references
- config-detail responses include parent and source provenance
- auto-promotion decisions include explicit rejection or promotion reasons

## Frontend requirements

The frontend must provide a dedicated plan-generation tuning workflow under research.

### Required pages

1. **Plan generation tuning overview page**
   - active config summary
   - automatic-mode state
   - latest run summary
   - quick links to runs and config history

2. **Tuning runs page**
   - paginated list of runs
   - filters for status, mode, date range, promotion outcome

3. **Run detail page**
   - candidate ranking table grouped by experiment/knob when the same knob-set produces multiple candidates
   - baseline vs winner comparison
   - eligibility and validation summary
   - guardrail pass/fail reasons
   - manual promote action if allowed

4. **Config history page**
   - version history
   - active/superseded status
   - rollback affordance where allowed

### Required UI safety behavior

- the UI must clearly distinguish `dry_run`, `manual_promote`, and `auto_promote`
- the UI must clearly label candidates that are rankable but not promotion-eligible
- the UI must show why a candidate failed promotion
- the UI must show the currently active config version at all times

## Job-system integration

If the project already uses a worker-backed job model, plan-generation tuning must integrate with that model rather than bypassing it.

Required behavior:
- scheduled and manual runs must both create durable job/run records
- active-run conflict prevention must exist
- failure state and cancellation state must be visible
- plan-generation tuning must have its own job type, not reuse a semantically different type unless the old type is renamed and repurposed cleanly

## Migration rules

Implementation must not silently repurpose legacy tables with different semantics.

Required approach:
- create new dedicated tables for plan-generation tuning
- remove the legacy weight-optimization job from supported workflows
- do not keep a parallel legacy optimizer path in the product surface

## Failure handling

The tuning system must fail safely.

### Required failure behavior

- a failed run must never partially activate a candidate config
- a failed auto-promotion attempt must leave the active config unchanged
- partial candidate evaluation is allowed only if the run is marked partial and no promotion occurs
- every failure must persist a human-readable error summary

## Observability requirements

Each run must persist enough metadata to diagnose behavior.

Required persisted metadata:
- code version or git SHA if available
- parameter schema version
- eligible sample summary
- holdout summary
- baseline metrics
- winning metrics
- promotion decision explanation
- skipped-reason explanation if no promotion occurred

## Acceptance criteria

The feature is complete only when all of the following are true.

### Backend

- dedicated persistence tables exist for runs, candidates, config versions, and events
- active config can be read atomically by live plan generation
- a manual dry-run endpoint exists
- a manual promote endpoint exists
- a state endpoint exists
- scheduled daily runs are supported
- auto-promotion obeys all guardrails in this spec
- candidate ranking is deterministic and auditable

### Frontend

- operators can inspect active config, run history, candidate rankings, and promotion results
- paginated views exist for runs and config history
- guardrail failures and rejection reasons are visible
- active config provenance is visible

### Safety

- automatic mode can run without supervision
- automatic mode cannot drift outside registered parameter schema
- automatic mode cannot promote candidates that fail sample-size, holdout, or guardrail checks
- rollback is supported and audited

## Explicit non-goals for the first implementation

The first implementation does not need:
- reinforcement learning
- black-box Bayesian optimization
- fully generic optimization across unrelated app domains
- self-modifying parameter-schema generation
- unsupervised mutation without bounded candidate limits

These may be considered later only after the deterministic bounded system is stable.

## Implementation order

Implementation should proceed in this order:

1. inspect the current legacy weight-optimization and plan-generation flow
2. define the tunable parameter schema and active-config loading path
3. add dedicated persistence tables and repositories
4. implement deterministic candidate generation and replay scoring
5. implement manual run and run-detail APIs
6. implement config-version promotion and rollback
7. wire live plan generation to the active config
8. add scheduled daily runs with auto-promotion guardrails
9. build the frontend review workflow
10. add route, repository, service, and integration coverage

## Amendment rule

Autonomous implementation must not broaden scope beyond this spec without an explicit user request if the change would affect:
- optimization objective order
- promotion policy
- sample eligibility rules
- parameter-schema boundaries
- persistence model semantics
- automatic-mode safety guarantees

## Related docs

- `recommendation-methodology.md`
- `recommendation-plan-resolution-spec.md`
- `archive/implementation-plans/recommendation-plan-evaluation-recompute-notes.md`
- `decision-sample-tuning-guide.md`
- `signal-gating-tuning-guide.md`
- `raw-details-reference.md`
- `operator-page-field-guide.md`
