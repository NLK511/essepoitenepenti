# Legacy Retirement Plan

## Purpose

This document defines how the app should retire legacy recommendation surfaces now that the redesign path is the only intended operator workflow.

The goal is no longer coexistence. The goal is to remove legacy recommendation-path maintenance and keep the product centered on redesign-native objects.

## Current retirement reality

Today the app still contains some legacy code and historical data, but the active proposal/evaluation workflow is redesign-native:
- watchlist-backed proposal jobs use the redesign orchestration path
- manual ticker proposal jobs also execute through redesign orchestration via an explicit synthetic watchlist wrapper (`1w`, shorts enabled)
- proposal runs persist `TickerSignalSnapshot` and `RecommendationPlan` objects as the canonical output path
- new redesign-backed proposal runs no longer emit legacy `Recommendation` rows as compatibility projections
- mounted operator evaluation and optimization now use `RecommendationPlanOutcome`
- run-detail/debugger operator flows no longer rely on legacy recommendation output payloads
- some sentiment snapshot workflows remain transitional, but legacy recommendation-detail/recommendation-history operator framing is already retired

## Canonical product direction

The canonical product path is:
1. context refresh
2. watchlist or ticker setup evaluation
3. `TickerSignalSnapshot`
4. `RecommendationPlan`
5. `RecommendationPlanOutcome`
6. calibration / baseline / operator review

Legacy `Recommendation` objects are no longer part of the intended proposal-generation path.

## Convergence principles

- do not retire a legacy path before the redesign path is observably usable
- do not keep duplicate concepts longer than necessary once the redesign path is stronger
- favor one clear operator truth path over parallel partially-overlapping systems
- retire claims and UI wording before or with code retirement, not long after

## Retirement decisions now in force

## 1. Manual ticker jobs
Decision:
- manual ticker jobs run through redesign-native orchestration and write redesign-native objects

## 2. Legacy recommendation rows
Decision:
- new proposal-generation runs should not emit legacy `Recommendation` compatibility rows
- legacy recommendation rows are not a long-term compatibility layer; remaining code around them is retirement-only cleanup rather than an endorsed compatibility path

## 3. Legacy operator surfaces
Decision:
- recommendation-detail and recommendation-history operator framing should be retired in favor of recommendation-plan views

## 4. UI terminology
Decision:
- operator surfaces should lead with:
  - context
  - ticker signal
  - recommendation plan
  - outcome

## Convergence milestones

## Milestone A: redesign-first operator truth
Achieved when operators can do most core review through redesign objects and views without needing legacy recommendation detail pages.

Current status:
- substantially achieved
- run detail, ticker-signal, recommendation-plan, calibration, and baseline workflows already expose most redesign-native operator review surfaces
- manual ticker jobs now also write redesign-native ticker signals and recommendation plans through an explicit synthetic watchlist wrapper
- mounted run-detail/debugger flows now treat recommendation plans and outcomes as canonical instead of surfacing legacy recommendation-output payloads
- the remaining convergence gap is no longer operator truth for proposal jobs, but the longer-tail cleanup of dormant legacy persistence/models plus transitional snapshot-first framing

## Milestone B: manual-path convergence
Achieved when manual ticker jobs can emit redesign-native ticker signals and recommendation plans with acceptable stability.

## Milestone C: legacy recommendation retirement
Achieved operationally when:
- legacy `Recommendation` rows are no longer emitted for new proposal workflows
- optimization no longer depends on legacy recommendation WIN/LOSS semantics
- no operator-facing flow depends on legacy recommendation objects
- legacy recommendation ORM/repository persistence code has been removed from the product path

Retirement cleanup decision now executed:
- the historical `recommendations` table is dropped through migration `0015_drop_legacy_recommendations_table`, so legacy recommendation retention no longer survives as hidden database baggage in the active app schema

## Milestone D: snapshot-flow narrowing
Achieved when remaining sentiment snapshot surfaces are either clearly transitional or replaced by context-first views.

## Preconditions before retiring legacy paths

These conditions are now sufficiently met for legacy recommendation-path retirement:
- redesign-native outputs are operator-visible
- evaluation/outcome persistence is working reliably
- deep analysis is sufficiently stable for the redesign path to be the default operator workflow
- core proposal workflows no longer need legacy-only fields
- documentation and API semantics are being updated to match the redesign-only posture

## Anti-patterns to avoid

Avoid:
- indefinite dual canonical models
- operator UIs that mix redesign and legacy terms without explanation
- retiring old flows before the new ones are reviewable
- claiming redesign completeness while manual jobs still bypass it

## Success criteria

Convergence is succeeding if:
- the primary product story becomes simpler
- operators know which objects are canonical
- fewer duplicated concepts remain
- new evaluation, calibration, and optimization logic consistently applies to `RecommendationPlan` / `RecommendationPlanOutcome`
- legacy recommendation data can be deleted without removing any active product capability
- any retention of the old `recommendations` table is treated as an explicit audit choice rather than a hidden product dependency
