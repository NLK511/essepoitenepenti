# Tuning workflow UX spec

**Status:** target behavior

This spec defines the operator UX for plan-generation tuning from candidate discovery through validation, promotion, and post-promotion monitoring.

It complements:
- `plan-generation-tuning-spec.md` for tuning semantics, ranking, parameter schema, and promotion rules
- `historical-playback-tuning-spec.md` for replay execution, cache-only point-in-time data rules, replay evidence tiers, and candidate replay validation

## Purpose

The tuning workflow page should give an operator one coherent path to answer:

> Which candidate configurations were discovered, which were validated, which are promotable, and what is the next safe action?

The page must cover the full lifecycle:

1. define experiment
2. audit evidence readiness
3. discover candidate configs
4. shortlist candidates
5. run or select baseline replay
6. run candidate replay validation
7. run walk-forward and holdout validation
8. generate promotion proposal
9. execute guarded promotion
10. monitor post-promotion performance

Raw replay batches, job runs, config versions, and search artifacts may remain on advanced pages, but the normal operator path must start from this workflow.

## Core concepts

### Tuning experiment

A tuning experiment is the parent context for all tuning evidence and decisions.

It should group:
- experiment name and notes
- hypothesis/objective
- universe definition
- training/discovery window
- replay validation window
- holdout window
- candidate discovery settings
- candidate shortlist
- baseline config and baseline replay batch
- candidate replay batches
- walk-forward results
- holdout replay batches
- promotion proposal
- promotion or rejection decision
- post-promotion monitoring summary

The first implementation may assemble this as a read model from existing tables, but the UX should behave as if the experiment is one object.

### Candidate validation depth

Every candidate must be assigned the cheapest causally valid validation depth before it can be queued.

Allowed depths:

- `rescore_only` — reuse generated plans and outcomes where candidate changes only a supported final scoring/actionability threshold.
- `frozen_input_plan_regeneration` — reuse frozen upstream replay evidence and regenerate only downstream plan construction plus outcome resolution. This is the default for plan-generation geometry/framing parameters.
- `full_orchestration_replay` — rerun cheap scan, deep analysis, signal generation, plan generation, and outcome resolution from local point-in-time inputs. This is required only when a candidate changes upstream selection/evidence behavior.

The UI must explain why each candidate received its depth and what work will be reused.

Examples:

| Candidate change | Required depth |
| --- | --- |
| final actionability floor only | `rescore_only` |
| entry band, stop multiplier, take-profit multiplier | `frozen_input_plan_regeneration` |
| universe/watchlist filtering | `full_orchestration_replay` or explicitly documented filtered-artifact replay when semantics allow |
| cheap-scan threshold, shortlist aggressiveness, deep-analysis inclusion | `full_orchestration_replay` |

### Candidate lifecycle states

Each candidate should move through explicit states:

1. `discovered` — generated/imported as a possible config
2. `shortlisted` — selected for expensive validation
3. `replay_running` — candidate replay is queued/running
4. `replay_validated` — main replay completed and compared to baseline
5. `stability_validated` — walk-forward and/or holdout completed
6. `promotion_proposed` — promotion report exists
7. `promoted` — paper/live guarded config created
8. `rejected` — rejected with reason
9. `archived` — no longer active

Discovery evidence is never sufficient for promotion.

## Required operator inputs

The experiment setup form must require these fields.

### Experiment name

Human-readable name, for example:

`July US250 plan-generation tuning`

### Universe

The ticker universe to test.

Allowed forms:
- named watchlist / existing watchlist ID (implemented for setup, readiness audit, and replay batch creation)
- explicit ticker list (implemented)
- existing replay universe
- cloned universe from previous experiment

The operator should be able to specify:
- included tickers
- excluded tickers
- whether repeated bar-gap tickers may be automatically proposed for pruning
- whether degraded data is allowed or blocks validation

### Time windows

The operator must define at least:
- discovery/training window
- main replay validation window
- holdout window

Optional:
- post-promotion paper-trial monitoring window

Rules:
- training/search windows must end before validation windows when used for model/candidate selection
- holdout must not overlap the discovery window
- holdout should not be reused repeatedly as an informal training set without warning
- windows should display expected resolvability based on available outcome horizon

### Candidate discovery search size

The operator must define the discovery budget.

Recommended presets:
- `small` — safe default for VPS use
- `medium` — still bounded; requires operator confirmation
- `custom` — advanced only

Custom fields:
- coarse candidate count
- fine/refinement candidate count
- random seed, if any stochastic source is used
- maximum changed keys per candidate
- maximum step distance from baseline

Default UX guidance:
- prefer small candidate sets
- avoid brute-force sweeps on the small VPS
- large searches are discovery-only and not promotion evidence

### Candidate amount for replay pass

The operator must define how many candidates can enter expensive replay validation.

Fields:
- max candidates to replay
- max replay batches to queue
- replay ordering priority

Default:
- `5` candidates

Allowed range should normally guide the operator toward `5–10` candidates unless the deployment has more resources.

### Primary objective

The operator must choose how candidates are ranked.

Allowed objectives:
- maximize Tier A actionable win rate
- maximize expected value / normalized return
- maximize average 5d return
- minimize loss severity / drawdown proxy
- balanced score

The UI must show that objective selection affects shortlist ranking and promotion reports.

If no objective is selected, the workflow must not claim a candidate is “best”.

### Baseline selection

The operator must choose the baseline source:
- current active/promoted config
- selected config version
- existing replay batch
- rerun baseline replay

A candidate comparison is invalid until the baseline is known.

### Promotion target

The operator must choose the intended promotion scope:
- research only
- paper config
- live guarded config
- live full autonomy

Default:
- `paper config`

`live full autonomy` should remain disabled unless autonomy gates in the relevant specs are fully implemented and passing.

## Advanced operator inputs

Advanced settings should be grouped in collapsible sections and default conservatively.

### Candidate sources

The operator may enable or disable candidate sources:
- import prior large-search winners
- run fresh bounded search
- use manual configs
- generate stricter quality-gate variants
- generate risk/reward geometry variants
- generate universe-filter variants
- run actionability-floor replay-artifact rescore, only for supported threshold-only changes

Every source must display:
- what data it uses
- whether it regenerates plans
- whether it is promotion-capable
- expected runtime/cost

### Parameter bounds

The operator may constrain allowed search ranges:
- actionability/confidence floor ranges
- entry band ranges
- stop multiplier ranges
- take-profit multiplier ranges
- setup-family-specific ranges
- maximum deviation from baseline

Unknown/unregistered parameter keys must be rejected.

### Validation gates

The operator may adjust, within safe bounds:
- minimum Tier A sample size
- minimum resolved/actionable count
- minimum distinct market days
- minimum distinct tickers
- minimum improvement vs baseline
- minimum holdout improvement
- maximum ticker concentration
- maximum setup-family concentration
- maximum missing-data ratio
- whether holdout replay is required

Defaults must match or be stricter than the promotion rules in `plan-generation-tuning-spec.md` unless the experiment is marked research-only.

### Replay input access policy

Replay and replay-derived validation must use local point-in-time stores only.

Rules:
- historical bars come from the local bars store
- news comes from `historical_news` only, bounded by `published_at <= as_of` and `available_at <= as_of` where available
- social/context/fundamental/market-intelligence inputs come from local snapshots only, bounded by their point-in-time timestamps
- missing local coverage creates readiness warnings or hard blocks according to data-quality policy
- remote provider fetches are not allowed inside replay execution or candidate validation

Remote fetching/backfill may be offered only as a separate explicit hydration job before replay.

### Data-quality policy

Fields:
- minimum bar coverage
- maximum Tier C ratio
- allow/disallow degraded coverage
- exclude repeated bar-gap tickers
- include/exclude tickers missing outcome windows
- fail experiment on cache gaps or only warn

Replay execution must remain cache-only. Missing bars should trigger readiness warnings or explicit backfill instructions, not remote fetching during replay.

### Replay execution limits

Fields:
- cache-only policy, displayed as enforced
- max concurrent replay workers
- max failed slices before stopping
- stale slice auto-recovery setting
- stop after current slice action
- resource profile: low / normal

Default for the small VPS:
- concurrency `1`
- resource profile `low`
- sequential candidate replay

### Evaluation horizons

Fields:
- primary ranking horizon: 1d, 3d, 5d, or normalized EV
- secondary warning horizons
- minimum horizon availability

Promotion reports must show candidate behavior across all available horizons, not only the primary one.

### Manual review policy

Fields:
- require human approval before promotion
- allow automatic paper proposal creation
- allow automatic paper promotion if all gates pass
- allow guarded live promotion

Defaults:
- human approval required
- automatic paper proposal allowed
- automatic live promotion disabled

### Stop conditions

Optional stop rules:
- stop if baseline replay is unusable
- stop if evidence readiness fails hard gates
- stop after N candidate replay failures
- stop if early candidates all underperform baseline by a configured margin
- stop on repeated infrastructure/resource errors

## Workflow page layout

The page should have a top lifecycle banner and one card per stage.

### Top lifecycle banner

Must show:
- experiment name
- current stage
- candidate funnel counts
- current recommendation
- next safe action
- blockers

Example:

```text
Experiment: July US250 tuning
Stage: Candidate replay validation
Candidate funnel: 37 discovered → 5 shortlisted → 2 replayed → 0 holdout-tested → 0 promotable
Recommendation: wait for remaining candidate replays
Next action: continue candidate replay batch #24
Promotion: blocked, validation incomplete
```

### Stage 1 — Experiment setup

Shows configured inputs and completeness.

Actions:
- create experiment
- clone experiment
- edit setup
- archive experiment

### Stage 2 — Evidence readiness

Shows whether the selected universe/windows are replayable.

Must include:
- cached bar coverage
- expected Tier A ratio
- repeated bar-gap tickers
- missing outcome-window warnings
- remote-fetch policy
- pruning recommendations

Actions:
- run readiness audit
- create watchlist pruning proposal
- accept current data risk, if allowed

### Stage 3 — Candidate discovery

Shows enabled sources and discovered candidate pool.

Actions:
- generate candidate pool
- import top N from search artifact
- add manual candidate
- deduplicate candidates

Candidate discovery outputs must be clearly labeled research-only.

### Stage 4 — Candidate shortlist

Shows candidate pool and selected validation set.

Must include per candidate:
- label
- source
- config diff vs baseline
- discovery score
- expected effect
- known risks
- selected/not selected
- validation status

Actions:
- select for replay
- reject candidate
- edit manual candidate
- compare configs

### Stage 5 — Baseline replay

Shows baseline config and baseline replay status.

Actions:
- run baseline replay
- resume baseline replay
- use existing batch as baseline
- view replay detail

Candidate validation must be blocked until the baseline is selected and either complete or explicitly accepted as reusable.

### Stage 6 — Candidate replay validation

Shows replay progress and candidate-vs-baseline metrics.

Must include:
- replay batch ids
- slice progress
- worker/run status
- Tier A/B/C counts
- wins/losses/no-entry/open counts
- win-rate delta vs baseline
- EV/return delta vs baseline
- concentration warnings
- data-quality warnings

Actions:
- run selected candidate replays
- resume failed/stale replays
- stop after current slice
- compare against baseline

### Stage 7 — Stability validation

Includes walk-forward and holdout checks.

Walk-forward must be labeled as a stability/overfit screen, not promotion proof by itself when it does not regenerate plans.

Holdout replay must be labeled as stronger promotion evidence because it regenerates plans on a separate window.

Actions:
- run walk-forward
- run holdout baseline replay
- run holdout candidate replay
- approve stability result

### Stage 8 — Promotion proposal

Automatically summarizes whether a candidate is promotable.

Must include a gate table:
- main replay sample gates
- main replay improvement gates
- holdout gates
- concentration gates
- data-quality gates
- stability gates
- promotion target eligibility

Actions:
- create paper config proposal
- reject proposal
- request more validation
- export promotion report

### Stage 9 — Promotion execution

Shows target config version and deployment scope.

Actions:
- promote to paper
- promote to guarded live, only if allowed
- schedule promotion
- rollback

Promotion must persist actor/mode, source config, target config, evidence links, reason, timestamp, and rollback config.

### Stage 10 — Post-promotion monitoring

Shows whether promoted config behaves acceptably after deployment.

Must include:
- active config version
- days active
- plans generated
- resolved outcomes
- win rate / EV / return metrics
- drift vs replay expectations
- rollback triggers
- current recommendation

Actions:
- extend paper trial
- rollback
- approve live guarded rollout
- open performance detail

## Computation labels

Every result card must disclose the computation type.

Required fields:
- computation type
- data used
- whether plans were regenerated
- whether outcome labels are canonical replay outcomes or stored outcomes
- whether the result is promotion-capable
- links to source artifacts

Examples:

```text
Computation type: full point-in-time replay
Uses: cached historical bars and replay-safe context available at as_of
Regenerates plans: yes
Promotion-capable: yes, after holdout and gates
```

```text
Computation type: large parameter search
Uses: existing eligible records/search artifact
Regenerates plans: no
Promotion-capable: no, discovery only
```

```text
Computation type: walk-forward validation
Uses: existing replay/stored resolved evidence
Regenerates plans: no
Promotion-capable: no by itself; stability filter only
```

```text
Computation type: actionability-floor replay-artifact rescore
Uses: one completed replay batch
Regenerates plans: no
Promotion-capable: only for supported threshold-only paper proposal, subject to gates
```

## Blocking rules

The UI must block or warn on unsafe transitions.

Block candidate replay when:
- no baseline is selected
- no candidates are shortlisted
- replay window is missing
- candidate config contains unknown keys
- replay is not configured cache-only

Block promotion proposal when:
- main candidate replay is incomplete
- baseline comparison is missing
- Tier A sample gates fail
- holdout is required but missing
- critical data-quality blockers exist
- candidate underperforms baseline according to selected objective/gates

Block live promotion when:
- promotion target is not live guarded/full autonomy
- required autonomy gates are not implemented/passing
- human approval is required and missing
- broker/risk-management gates fail

## Operator copy rules

The UI must avoid implying unproven edge.

Use:
- “discovered candidate” before replay
- “promising candidate” after main replay pass
- “holdout-tested candidate” after holdout replay
- “promotable candidate” only after all required gates pass

Do not use:
- “winner” for a discovery-only result
- “validated” for a candidate that only passed stored-plan search
- “safe to promote” unless the promotion proposal gate passes

## Initial implementation plan

1. Add this spec to the docs navigation if applicable.
2. Add a workflow read endpoint that groups existing replay batches, tuning runs, candidates, config versions, and promotion state by experiment or by explicit user selection.
3. Build a first `TuningWorkflowPage` with read-only lifecycle cards and deep links to existing pages.
4. Add experiment creation/edit form with the required inputs in this spec.
5. Add candidate shortlist management and replay queue actions.
6. Add promotion proposal summary using existing promotion rules and replay aggregates.
7. Move legacy raw controls on the current plan-generation tuning page behind an advanced/research label.

## Open questions

- Should experiments be persisted as a new table immediately, or should the first version infer them from replay batch naming/config metadata?
- Should holdout windows be manually selected only, or can the system recommend non-overlapping holdout windows from available cached coverage?
- Which objective should be the default for the next production workflow: Tier A win rate, 5d return, or balanced score?
