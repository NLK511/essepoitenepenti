# Research Actionability Floor Spec

Status: implemented

## Problem

After source-aware confidence calibration, live broker confidence is more honest but lower:

- broker-only calibration is usable;
- broker raw-rank health is still unstable;
- broker win rate is materially lower than simulation-only win rate;
- strict execution floors can prevent the app from producing enough actionable/research samples for future tuning.

One strict floor is the wrong abstraction. It mixes two different decisions:

1. Should the app execute a real broker trade?
2. Should the app create a fully specified plan so we can learn from its outcome?

Those decisions need separate thresholds.

## Goal

Create a two-floor plan-generation policy:

- keep live execution conservative;
- lower the data-collection floor for full shadow/research plans;
- preserve broker-only calibration for live actionability;
- collect structured outcomes for future tuning without pretending research samples are live-trade evidence.

## Non-Goals

- Do not lower the live broker execution floor just to increase activity.
- Do not treat simulation-only success as permission to trade live.
- Do not mutate calibrated confidence to make rejected plans appear stronger.
- Do not add new signal features in this change.
- Do not auto-promote tuning candidates from research samples alone.

## Definitions

### Execution floor

Strict threshold used for real broker execution.

Properties:

- source: broker-only calibrated probability;
- applies after EV/risk geometry checks;
- protects live and paper-broker order submission;
- promotion requires broker holdout evidence.

### Research plan floor

Lower threshold used to produce full non-executing plans.

Properties:

- creates entry, stop, take-profit, risk/reward, thesis, setup-family, calibrated-confidence, and rejection metadata;
- does not send broker orders;
- tracks future outcome as research/shadow evidence;
- feeds tuning and diagnostics.

### Shadow tracking floor

Even lower threshold for lightweight observation.

Properties:

- records candidate context and reason for rejection;
- may not require full trade geometry;
- useful for measuring whether shortlist/gating is too strict;
- does not count as actionability evidence.

### Exploration quota

Bounded allowance for borderline research plans.

Properties:

- count-limited per run/day;
- risk-limited;
- setup-family limited;
- date/ticker concentration limited;
- paper-only or no-execution by default.

## Proposed Policy Layers

```text
candidate signal
  -> calibrated broker probability
  -> EV / risk geometry
  -> execution floor
      pass: live/paper actionable candidate
      fail: continue
  -> research plan floor
      pass: full shadow/research plan with outcome tracking
      fail: continue
  -> shadow tracking floor / exploration quota
      pass: lightweight observation row
      fail: discard
```

## Initial Parameters

Add explicit plan-generation tuning parameters:

- `global.execution_confidence_floor_percent`
- `global.research_plan_floor_percent`
- `global.shadow_tracking_floor_percent`
- `global.research_plan_quota_per_run`
- `global.shadow_tracking_quota_per_run`
- `setup_family.<family>.research_floor_delta_percent`
- `setup_family.<family>.shadow_quota_weight`

Initial defaults should be conservative:

- execution floor: current effective actionability floor;
- research plan floor: execution floor minus 10-15 points;
- shadow tracking floor: research floor minus 5-10 points;
- research quota: small fixed count per run;
- shadow quota: larger than research quota, but still bounded.

Exact defaults must be validated against current plan volume before enabling.

## Plan State Model

Recommendation plans need a clear decision tier:

- `execution_candidate`
- `research_plan`
- `shadow_observation`
- `discarded`

Do not overload `action` alone. A `research_plan` may have intended action `long` or `short` but must not be eligible for broker execution.

Required persisted fields, either top-level or in `signal_breakdown` until schema migration is justified:

- `decision_tier`
- `intended_action`
- `execution_eligible`
- `research_eligible`
- `shadow_eligible`
- `floor_source`
- `execution_floor_percent`
- `research_floor_percent`
- `shadow_tracking_floor_percent`
- `calibration_source`
- `calibrated_probability_percent`
- `expected_value_estimate`
- `risk_reward_ratio`
- `rejection_reason`
- `would_have_executed_under_policy_version`

## Outcome Tracking

Research plans must be resolved with the same simulated/effective outcome machinery, but source labels must stay explicit:

- broker outcomes: live/paper execution evidence;
- simulation outcomes: research evidence;
- shadow observations: observation evidence, not actionability evidence.

Research outcome artifacts must include:

- entry touched;
- near-entry miss;
- max favorable excursion;
- max adverse excursion;
- stop/take-profit hit status;
- horizon return;
- realized or simulated R multiple;
- source label;
- plan tier.

## Tuning Use

Large tuning searches may use research plans for discovery, but promotion must remain broker-gated.

Allowed:

- use research plans to estimate whether lower floors produce enough viable candidates;
- use research plans to compare geometry and EV hypotheses;
- use simulation-only evidence to rank candidates for further broker validation.

Blocked:

- direct live promotion from simulation-only improvement;
- direct live promotion from research-plan WR alone;
- confidence-boost tuning;
- selecting a candidate whose broker holdout worsens.

Promotion candidates must report:

- broker-only actionability count, WR, EV, Brier, ECE;
- research-plan count, WR, EV, MFE/MAE;
- simulation-only diagnostics;
- date/ticker/setup concentration;
- delta versus baseline for execution candidates and research plans separately.

## UI / Operator Reporting

The UI should separate:

- executable plans;
- research plans;
- shadow observations.

A research plan should be inspectable like a normal plan but visually and semantically non-executable.

Required filters:

- decision tier;
- execution eligibility;
- research eligibility;
- shadow eligibility;
- rejection reason;
- calibration source;
- setup family;
- confidence bucket;
- EV/R multiple bucket.

## Safety Gates

Execution safety:

- research and shadow tiers must never submit broker orders;
- live/paper order execution must check `execution_eligible` directly;
- broker steering must ignore research-only plans for autonomous order action.

Data quality:

- research samples must not contaminate broker-only calibration;
- research samples must be labeled separately in tuning artifacts;
- promotion must fail if source labels are missing.

Sample quality:

- quota prevents one date/ticker/setup family from dominating;
- research plans must include enough geometry to evaluate EV, not just direction;
- shadow observations that lack geometry are excluded from EV tuning.

## Implementation Phases

### Phase 1 - Spec and Data Contract

- Add the decision-tier contract.
- Add floor parameter names and default semantics.
- Add artifact fields for execution/research/shadow thresholds.
- Update tests for tier classification and broker-execution exclusion.

### Phase 2 - Plan Framing

- Modify plan framing so threshold failures can become `research_plan` instead of plain `no_action` when above the research floor.
- Persist full trade geometry for research plans.
- Preserve rejection reason and effective threshold details.
- Add quotas for research and shadow samples.

### Phase 3 - Outcome Tracking

- Ensure research plans are resolved by existing outcome refresh.
- Mark outcomes with plan tier.
- Add summary cohorts by decision tier.
- Exclude research/shadow tiers from broker-only calibration.

### Phase 4 - Tuning Workflow

- Add source-aware dry-run tuning mode for two-floor policy.
- Rank candidates on execution evidence first, research evidence second.
- Add explicit promotion blockers when improvement is research-only.

### Phase 5 - UI and Reporting

- Add filters and labels for execution/research/shadow tiers.
- Show research plans as non-executable.
- Add data-collection metrics: generated research plans, resolved research plans, research EV, and broker conversion rate.

## Acceptance Criteria

1. A plan below execution floor but above research floor is persisted as non-executable research evidence.
2. Research plans never submit broker orders.
3. Research outcomes resolve and appear in diagnostics.
4. Broker-only calibration excludes research/shadow evidence unless there is actual broker execution.
5. Large tuning reports separate execution evidence from research evidence.
6. Promotion is blocked when improvement is simulation/research-only.
7. Operator UI can distinguish executable plans from research plans at a glance.

## Open Questions

- Should research plans use the same `recommendation_plans` table with a `decision_tier`, or a separate research table?
- Should paper-broker exploratory orders be a later phase or remain fully disabled until broker-only WR improves?
- What exact first default should be used for `research_plan_floor_percent` after measuring current plan volume?
- Should exploration quota be global, per setup family, or both?

## Recommended First Implementation

Implemented with the least risky path:

1. Use existing `recommendation_plans` with `decision_tier` stored in `signal_breakdown`.
2. Add research and shadow floor parameters to plan-generation tuning config.
3. Generate full research plans but force `execution_eligible=false`.
4. Resolve outcomes with existing simulation/effective-outcome machinery.
5. Add tier-separated reporting before changing any live execution behavior.

Only after that should we consider paper-broker exploration.
