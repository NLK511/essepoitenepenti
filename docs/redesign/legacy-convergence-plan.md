# Legacy Convergence Plan

## Purpose

This document defines how the app should converge from coexistence between legacy and redesign paths toward a clearer end state.

The goal is not to remove legacy code as fast as possible. The goal is to retire or narrow legacy paths when the redesign path is operationally and evaluatively stronger.

## Current coexistence reality

Today the app still has both:
- legacy sentiment/snapshot-oriented workflows
- redesign-native watchlist/context/recommendation-plan workflows

Current practical split:
- watchlist-backed proposal jobs already use the redesign orchestration path
- manual ticker proposal jobs still use the legacy path
- some sentiment snapshot workflows remain transitional
- legacy `Recommendation` rows still exist for compatibility and some existing surfaces

## Canonical future direction

The intended canonical product path should be:
1. context refresh
2. watchlist or ticker setup evaluation
3. `TickerSignalSnapshot`
4. `RecommendationPlan`
5. `RecommendationPlanOutcome`
6. calibration / baseline / operator review

Legacy `Recommendation` should ultimately become either:
- a compatibility projection
- or a narrow legacy-only artifact pending retirement

## Convergence principles

- do not retire a legacy path before the redesign path is observably usable
- do not keep duplicate concepts longer than necessary once the redesign path is stronger
- favor one clear operator truth path over parallel partially-overlapping systems
- retire claims and UI wording before or with code retirement, not long after

## Required decisions

## 1. Manual ticker jobs
Decision needed:
- should manual ticker jobs converge onto redesign-native deep analysis and `RecommendationPlan` generation?

Recommended default:
- yes, once redesign-native deep analysis is operationally stable and outcome review is acceptable

## 2. Sentiment snapshot workflows
Decision needed:
- which snapshot workflows remain first-class, transitional, or deprecated?

Recommended default:
- keep macro/industry refresh only where they support redesign context objects
- narrow or retire snapshot-first operator framing over time

## 3. Legacy recommendation rows
Decision needed:
- should legacy `Recommendation` remain canonical?

Recommended default:
- no; `RecommendationPlan` should become canonical for redesign workflows
- keep legacy rows only as compatibility projections until dependent surfaces are migrated

## 4. UI terminology
Decision needed:
- which surfaces should lead with context/plans/outcomes versus sentiment/recommendation legacy language?

Recommended default:
- redesign surfaces should lead with:
  - context
  - ticker signal
  - recommendation plan
  - outcome

## Convergence milestones

## Milestone A: redesign-first operator truth
Achieved when operators can do most core review through redesign objects and views without needing legacy recommendation detail pages.

Current status:
- partially achieved
- run detail, ticker-signal, recommendation-plan, calibration, and baseline workflows already expose most redesign-native operator review surfaces
- the remaining major gap is that manual ticker jobs still bypass the redesign-native truth path

## Milestone B: manual-path convergence
Achieved when manual ticker jobs can emit redesign-native ticker signals and recommendation plans with acceptable stability.

## Milestone C: compatibility-only legacy recommendations
Achieved when legacy `Recommendation` rows are no longer the primary internal truth for new workflows.

## Milestone D: legacy-path retirement decision
Achieved when enough measured evidence exists to choose whether to:
- retire legacy flows
- narrow them sharply
- or keep a limited fallback posture intentionally

## Preconditions before retiring legacy paths

Do not retire key legacy paths until:
- redesign-native outputs are operator-visible
- evaluation/outcome persistence is working reliably
- deep analysis is sufficiently stable
- core workflows no longer depend on legacy-only fields
- documentation and API semantics are updated

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
- new evaluation and calibration logic consistently applies to the main recommendation path
