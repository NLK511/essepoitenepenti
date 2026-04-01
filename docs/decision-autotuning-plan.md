# Decision autotuning plan

**Status:** development implementation plan

This document describes a first-pass autonomous tuning loop for recommendation decisions.

The goal is to let the app tune itself during development by using stored decision samples and outcomes to search a small parameter space, score candidate configurations, and write the best one back into active tuning settings.

## Current implementation snapshot

This is a **development-only target plan**, not a live product capability.

### Implemented so far
- a first-pass raw grid-search autotune service for recommendation tuning
- multi-parameter candidate scoring over confidence offset, calibration adjustment, near-miss promotion, shortlist aggressiveness, and degraded penalty
- persistence for autotune runs, summary data, and candidate comparison results
- a manual backend trigger at `POST /api/recommendation-autotune/run`
- a state endpoint at `GET /api/recommendation-autotune`
- apply / dry-run support, with apply writing the winning tuning values back into active settings
- live proposal-generation/scoring now reads the active autotune config and uses it in shortlist thresholds and calibration thresholds
- unit and route coverage for scoring, persistence, apply behavior, and live-path integration

### Current scope
- the autotune run now persists a broader active tuning config, even where downstream consumers do not yet use every field

### Expected future work
- candidate generation and scoring over a broader parameter grid than confidence threshold alone
- a read-only review page for comparing the latest run and its candidates
- richer scoring explanations and comparison summaries
- production scheduling or automatic rollout behavior

### Not yet implemented
- a UI control surface for launching or reviewing tuning runs
- adaptive optimization beyond the initial raw search pass
- production scheduling or automatic rollout behavior

This plan assumes:
- development-only usage
- no production rollout risk
- a desire for a simple, inspectable first pass rather than a sophisticated optimizer

## What this is for

The first version of autotuning should answer:

- is the current threshold too strict or too loose?
- are near-misses being rejected too often?
- are weak or degraded cases slipping through?
- does one setup family need different treatment?

The output should be a new tuning configuration, plus a full record of what was tested and how each candidate scored.

## What to tune first

Keep the initial tuning surface small.

Suggested parameters:
- confidence threshold offset
- calibration adjustment
- near-miss gap cutoff
- shortlist promotion bonus or aggressiveness
- degraded-input penalty

Avoid tuning many unrelated dimensions at once.

## Data sources

The tuner should read:

- `RecommendationDecisionSample`
- `RecommendationPlanOutcome`
- optionally `RecommendationPlan` for plan-side context

Join samples to outcomes by `recommendation_plan_id`.

## Core workflow

### 1. Load historical inputs

Collect the sample set to tune against, optionally filtered by:
- run
- ticker
- setup family
- date window

### 2. Generate candidate configurations

Use a small, explicit candidate grid.

Example knobs:
- threshold offset: `[-6, -4, -2, 0, +2]`
- calibration adjustment: `[-4, -2, 0, +2]`
- near-miss cutoff: `[-8, -5, -3]`
- shortlist aggressiveness: `[0, 1, 2]`

A grid search is the right first step because it is deterministic and easy to inspect.

### 3. Simulate candidate behavior

For each candidate configuration, estimate how each sample would behave under that config:

- would it become actionable?
- would it remain a near miss?
- would it be rejected earlier?
- would degraded data still be blocked?

### 4. Score each candidate

Use a weighted objective instead of a single metric.

Possible score components:
- win rate
- average return
- direction correctness
- calibration quality
- action selectivity
- degraded-rate penalty
- overtrading penalty

A simple first objective is enough as long as it is reproducible.

### 5. Choose the best config

Pick the highest-scoring candidate and store:
- the baseline score
- the winning score
- the winning config
- top-N candidate results
- score breakdown details

### 6. Optionally apply the winner

Support two modes:
- **dry run**: score and persist results only
- **apply**: write the winning config into active tuning settings

Dry run should be the default at first.

## Suggested implementation shape

### Service
Add a dedicated service such as:
- `DecisionAutotuneService`
- or `RecommendationAutotuneService`

Responsibilities:
- load samples and outcomes
- generate candidate configs
- score each candidate
- select the winner
- persist the run summary
- optionally apply the result

### Persistence
Store each tuning run with:
- start and completion timestamps
- status
- objective name
- sample counts
- candidate count
- baseline score
- best score
- best config JSON
- candidate results JSON
- optional filters used

### API or job entry point
Expose a manual trigger first, such as:
- `POST /api/recommendation-autotune/run`

A job-based execution path can follow later if useful.

### UI
Add a simple review page that shows:
- latest autotune run
- active config
- candidate comparison table
- best-vs-baseline delta
- apply button for the winning config

## Recommended implementation order

1. define the tuning config model
2. add autotune run persistence
3. implement the candidate scoring engine
4. wire a manual backend endpoint
5. build a read-only review page
6. add apply mode
7. add tests for scoring and persistence

## Success criteria

The first version is done when it can:

- run a deterministic tuning pass on historical samples
- produce a reproducible winning configuration
- show the full candidate comparison
- optionally write the winner into active settings
- explain why the winner was selected

## Important constraint

This plan is intended for development use.

The first objective is to learn a reasonable raw configuration, not to build a fully autonomous production optimizer.

## Related docs

- `recommendation-methodology.md`
- `decision-sample-tuning-guide.md`
- `raw-details-reference.md`
- `docs-index.md`
